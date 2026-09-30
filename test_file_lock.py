"""Real process contention and recovery, using isolated temporary lock files."""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from file_lock import exclusive_file_lock


ROOT = Path(__file__).resolve().parent
WRAPPERS = (
    ('agent', 'run_lock', 'run.lock', 'OSError'),
    ('pipeline', '_worker_lock', 'pipeline.lock', 'RuntimeError'),
    ('reading', 'worker_lock', 'reading.worker.lock', 'WorkerBusy'),
    ('github_resources', 'collection_lock', 'github.lock', 'GitHubBusy'),
    ('lab', 'file_lock', 'nested/lab.lock', 'LabBusy'),
)


class FileLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def child(self, code, *args):
        return subprocess.run([sys.executable, '-c', code, *map(str, args)], cwd=ROOT,
                              capture_output=True, text=True, timeout=15,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def test_all_wrappers_compete_across_processes_and_keep_busy_errors(self):
        for module, name, filename, error in WRAPPERS:
            with self.subTest(module=module):
                path = self.directory / filename
                path.parent.mkdir(exist_ok=True)
                code = (f'from {module} import {name}\nfrom pathlib import Path\nimport sys\n'
                        + (f'from {module} import {error}\n' if error.endswith('Busy') else '')
                        + f'try:\n    with {name}(Path(sys.argv[1])): pass\n'
                        + f'except {error}: sys.exit(23)\n')
                argument = path if module == 'lab' else self.directory
                with exclusive_file_lock(path):
                    blocked = self.child(code, argument)
                    self.assertEqual(blocked.returncode, 23, blocked.stderr)
                acquired = self.child(code, argument)
                self.assertEqual(acquired.returncode, 0, acquired.stderr)

    def test_body_errors_are_not_busy_errors_and_release_the_lock(self):
        path = self.directory / 'failure.lock'
        error = OSError('original business failure')
        with self.assertRaises(OSError) as caught:
            with exclusive_file_lock(path, lambda: RuntimeError('busy')):
                raise error
        self.assertIs(caught.exception, error)
        with exclusive_file_lock(path):
            pass

    def test_independent_locks_do_not_block_each_other(self):
        with exclusive_file_lock(self.directory / 'a.lock'):
            child = self.child('from file_lock import exclusive_file_lock\nimport sys\n'
                               'with exclusive_file_lock(sys.argv[1]): pass', self.directory / 'b.lock')
            self.assertEqual(child.returncode, 0, child.stderr)

    def test_killed_worker_releases_os_lock(self):
        path, ready = self.directory / 'worker.lock', self.directory / 'ready'
        code = ('from file_lock import exclusive_file_lock\nfrom pathlib import Path\nimport sys,time\n'
                'with exclusive_file_lock(sys.argv[1]):\n'
                '    Path(sys.argv[2]).write_text("ready")\n    time.sleep(30)\n')
        child = subprocess.Popen([sys.executable, '-c', code, str(path), str(ready)], cwd=ROOT,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), 'Worker did not acquire lock')
            with self.assertRaises(OSError):
                with exclusive_file_lock(path):
                    pass
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        with exclusive_file_lock(path):
            pass


if __name__ == '__main__':
    unittest.main()

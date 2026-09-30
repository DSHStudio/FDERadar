"""Nonblocking process locks; business recovery remains with each caller."""
from contextlib import contextmanager
import os
from pathlib import Path


@contextmanager
def exclusive_file_lock(path, busy_error=None):
    path = Path(path)
    with path.open('a+b') as handle:
        try:
            if path.stat().st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if busy_error is not None:
                raise busy_error() from exc
            raise
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

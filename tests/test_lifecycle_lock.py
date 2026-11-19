from pathlib import Path
import errno
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = ROOT / "scripts" / "workbench"
sys.path.insert(0, str(WORKBENCH_ROOT))

from xhs_research import lifecycle_lock


class FakeMsvcrt:
    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def locking(self, fd, mode, length):
        self.calls.append((fd, mode, length))
        if self.error is not None:
            raise self.error


class LifecycleLockTests(unittest.TestCase):
    def test_windows_backend_is_used_when_fcntl_is_unavailable(self):
        backend = FakeMsvcrt()
        with tempfile.TemporaryFile(mode="w+") as handle, \
                patch.object(lifecycle_lock, "_fcntl", None), \
                patch.object(lifecycle_lock, "_msvcrt", backend):
            lifecycle_lock.acquire_file_lock(handle)
            lifecycle_lock.release_file_lock(handle)

        self.assertEqual([call[1:] for call in backend.calls], [
            (backend.LK_NBLCK, 1), (backend.LK_UNLCK, 1),
        ])

    def test_windows_lock_contention_has_a_portable_exception(self):
        backend = FakeMsvcrt(OSError(errno.EACCES, "locked"))
        with tempfile.TemporaryFile(mode="w+") as handle, \
                patch.object(lifecycle_lock, "_fcntl", None), \
                patch.object(lifecycle_lock, "_msvcrt", backend):
            with self.assertRaises(lifecycle_lock.FileLockUnavailable):
                lifecycle_lock.acquire_file_lock(handle)


if __name__ == "__main__":
    unittest.main()

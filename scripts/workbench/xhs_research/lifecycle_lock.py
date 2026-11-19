"""Portable non-blocking process lock for a workbench data directory."""

import errno

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised on Windows and by patched tests
    _fcntl = None

try:  # Windows
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX
    _msvcrt = None


class FileLockUnavailable(RuntimeError):
    pass


def acquire_file_lock(handle):
    """Acquire an exclusive non-blocking lock while keeping ``handle`` open."""
    if _fcntl is not None:
        try:
            _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            raise FileLockUnavailable from exc
        return

    if _msvcrt is not None:
        # msvcrt.locking locks a byte range starting at the current offset.
        # Ensure byte zero exists before asking Windows for that range.
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write("\n")
            handle.flush()
        handle.seek(0)
        try:
            _msvcrt.locking(handle.fileno(), _msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            raise FileLockUnavailable from exc
        return

    raise RuntimeError("当前 Python 运行时不支持安全的进程文件锁")


def release_file_lock(handle):
    if _fcntl is not None:
        _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)
        return
    if _msvcrt is not None:
        handle.seek(0)
        _msvcrt.locking(handle.fileno(), _msvcrt.LK_UNLCK, 1)
        return
    raise RuntimeError("当前 Python 运行时不支持安全的进程文件锁")

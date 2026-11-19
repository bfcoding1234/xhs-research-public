import os
import signal
import subprocess
import time
from typing import Callable, Optional, Sequence, Tuple


class CodexProcessCancelled(RuntimeError):
    """Raised after a running Codex process has been stopped on request."""


def _signal_process_group(process: subprocess.Popen, force: bool) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif force:
            process.kill()
        else:
            process.terminate()
    except ProcessLookupError:
        return
    except OSError:
        if process.poll() is None:
            (process.kill if force else process.terminate)()


def _stop_process(process: subprocess.Popen, grace_seconds: float) -> Tuple[str, str]:
    """Terminate, then kill and reap a process without leaving its pipes open."""
    grace_seconds = max(0.01, float(grace_seconds))
    _signal_process_group(process, force=False)
    try:
        return process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired as terminate_timeout:
        _signal_process_group(process, force=True)
        try:
            return process.communicate(timeout=grace_seconds)
        except subprocess.TimeoutExpired as kill_timeout:
            # A descendant outside the process group can keep inherited pipes open.
            # Close our copies so reaping the killed Codex parent remains bounded.
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Codex process did not stop after SIGKILL") from exc
            stdout = kill_timeout.output or terminate_timeout.output or ""
            stderr = kill_timeout.stderr or terminate_timeout.stderr or ""
            return stdout, stderr


def run_codex_process(
    args: Sequence[str],
    prompt: str,
    timeout: float,
    should_cancel: Optional[Callable[[], bool]] = None,
    poll_interval: float = 0.1,
    terminate_grace: float = 1.0,
) -> subprocess.CompletedProcess:
    """Run Codex with cooperative cancellation and bounded timeout cleanup."""
    cancel_requested = should_cancel or (lambda: False)
    if cancel_requested():
        raise CodexProcessCancelled("Codex task cancelled")

    popen_options = {}
    if os.name == "posix":
        popen_options["start_new_session"] = True
    process = subprocess.Popen(
        list(args),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **popen_options,
    )
    deadline = time.monotonic() + max(0.0, float(timeout))
    pending_input = prompt
    try:
        while True:
            if cancel_requested():
                _stop_process(process, terminate_grace)
                raise CodexProcessCancelled("Codex task cancelled")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stdout, stderr = _stop_process(process, terminate_grace)
                raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)

            try:
                stdout, stderr = process.communicate(
                    input=pending_input,
                    timeout=min(max(0.01, poll_interval), remaining),
                )
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                pending_input = None
    except BaseException:
        if process.poll() is None:
            _stop_process(process, terminate_grace)
        raise

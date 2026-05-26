"""Track external child processes so app shutdown can stop them."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Sequence
from typing import Any

from loguru import logger as log

_LOCK = threading.Lock()
_PROCS: set[subprocess.Popen] = set()


def register_process(proc: subprocess.Popen) -> subprocess.Popen:
    with _LOCK:
        _PROCS.add(proc)
    return proc


def unregister_process(proc: subprocess.Popen) -> None:
    with _LOCK:
        _PROCS.discard(proc)


def popen_tracked(*args: Any, **kwargs: Any) -> subprocess.Popen:
    return register_process(subprocess.Popen(*args, **kwargs))


def run_tracked(
    args: Sequence[str],
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    capture_output = kwargs.pop("capture_output", False)
    stdout = subprocess.PIPE if capture_output else kwargs.pop("stdout", None)
    stderr = subprocess.PIPE if capture_output else kwargs.pop("stderr", None)
    proc = popen_tracked(
        args,
        stdout=stdout,
        stderr=stderr,
        text=kwargs.pop("text", None),
        encoding=kwargs.pop("encoding", None),
        errors=kwargs.pop("errors", None),
        cwd=kwargs.pop("cwd", None),
        stdin=kwargs.pop("stdin", None),
    )
    timeout = kwargs.pop("timeout", None)
    if kwargs:
        raise TypeError(f"Unsupported run_tracked kwargs: {sorted(kwargs)}")
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        terminate_registered_processes(force=True)
        raise
    finally:
        unregister_process(proc)


def terminate_registered_processes(force: bool = True) -> int:
    """Terminate all tracked subprocesses. Returns count signaled."""
    with _LOCK:
        procs = list(_PROCS)
    stopped = 0
    for proc in procs:
        if proc.poll() is not None:
            unregister_process(proc)
            continue
        try:
            if force:
                proc.kill()
            else:
                proc.terminate()
            stopped += 1
            log.info(f"Stopped child process pid={proc.pid}")
        except Exception as e:
            log.warning(f"Could not stop child process pid={getattr(proc, 'pid', '?')}: {e}")
        finally:
            unregister_process(proc)
    return stopped

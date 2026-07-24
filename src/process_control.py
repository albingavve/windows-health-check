"""Process termination ("End Task") — the first non-read-only action in
this codebase (see CLAUDE.md's safety rules: read-only by default, every
other action logged and reversible where possible; termination is
explicitly the one action that can't be undone, so it gets its own
module rather than living in collectors/process_list.py, which is pure
read-only data gathering with no side effects).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

import psutil

# Case-insensitive-matched list of process names this tool will never
# attempt to terminate: OS-critical kernel/session processes plus the
# handful of always-present, security-sensitive services. This is checked
# FIRST, before any mutating psutil call (.terminate()/.kill()) is even
# attempted.
#
# Windows' own permission model will often refuse to terminate several of
# these anyway — lsass.exe/lsaiso.exe run as Protected Process Light,
# smss.exe/csrss.exe/wininit.exe/services.exe/winlogon.exe are
# SYSTEM-owned session/subsystem processes a normal user token can't open
# with PROCESS_TERMINATE access — but that OS-level refusal is not
# something this tool relies on as its only line of defense. This
# hardcoded list is a deliberate, explicit first line of defense that
# runs regardless of what the OS access check would have allowed, and
# regardless of whether a future psutil/Windows change ever makes one of
# these unexpectedly terminable.
PROTECTED_PROCESSES = [
    "System Idle Process", "System", "Registry", "Secure System",
    "Memory Compression", "smss.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "lsaiso.exe",
    "fontdrvhost.exe", "dwm.exe", "svchost.exe", "WUDFHost.exe",
    "audiodg.exe", "spoolsv.exe",
]
_PROTECTED_NAMES_LOWER = {name.lower() for name in PROTECTED_PROCESSES}

# How long to wait after a graceful terminate() before escalating to a
# forceful kill().
TERMINATE_GRACE_PERIOD_SECONDS = 3.0
# kill() is a hard TerminateProcess call and should take effect almost
# immediately — this just confirms it actually did before reporting a
# timeout outcome.
KILL_WAIT_SECONDS = 2.0

_LOG_PATH = Path(__file__).resolve().parent.parent / "process_actions.log"


def is_protected(name: str | None) -> bool:
    """Case-insensitive membership check against PROTECTED_PROCESSES."""
    if not name:
        return False
    return name.strip().lower() in _PROTECTED_NAMES_LOWER


class TerminationOutcome(str, Enum):
    SUCCESS = "success"
    PROTECTED = "protected"
    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class TerminationResult:
    outcome: TerminationOutcome
    pid: int
    name: str | None
    message: str

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "pid": self.pid,
            "name": self.name,
            "message": self.message,
        }


def _log_attempt(pid: int, name: str | None, result: TerminationResult) -> None:
    """Append one line per termination attempt to a local log file (kept
    out of git via the existing `*.log` .gitignore entry). Best-effort —
    a logging failure (e.g. read-only filesystem) must not stop the
    result from being reported back to the caller."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    line = f"{timestamp}\tpid={pid}\tname={name or 'unknown'}\toutcome={result.outcome.value}\tmessage={result.message}\n"
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(line)
    except OSError:
        pass


def terminate_process(pid: int) -> TerminationResult:
    """Attempt to end a single process by PID.

    Order of operations matters: the protected-list check happens before
    any mutating call (.terminate()/.kill()) is attempted — identifying
    the process by name first is an unavoidable, read-only lookup against
    the OS's own process table (not client-supplied input), and is not
    itself a termination attempt.

    Graceful terminate() is tried first, with up to
    TERMINATE_GRACE_PERIOD_SECONDS to exit on its own, before escalating
    to a forceful kill().
    """
    try:
        process = psutil.Process(pid)
        name = process.name()
    except psutil.NoSuchProcess:
        result = TerminationResult(TerminationOutcome.NOT_FOUND, pid, None, f"No process with PID {pid} was found.")
        _log_attempt(pid, None, result)
        return result
    except psutil.AccessDenied:
        result = TerminationResult(
            TerminationOutcome.ACCESS_DENIED, pid, None, f"Access denied while inspecting PID {pid}."
        )
        _log_attempt(pid, None, result)
        return result

    if is_protected(name):
        result = TerminationResult(
            TerminationOutcome.PROTECTED,
            pid,
            name,
            f'"{name}" is a protected system process and cannot be ended from here.',
        )
        _log_attempt(pid, name, result)
        return result

    try:
        process.terminate()
        try:
            process.wait(timeout=TERMINATE_GRACE_PERIOD_SECONDS)
        except psutil.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=KILL_WAIT_SECONDS)
            except psutil.TimeoutExpired:
                result = TerminationResult(
                    TerminationOutcome.TIMEOUT,
                    pid,
                    name,
                    f'"{name}" (PID {pid}) did not exit even after a forceful kill.',
                )
                _log_attempt(pid, name, result)
                return result
    except psutil.NoSuchProcess:
        # Exited on its own between our lookup and terminate()/kill() —
        # the end state the caller wanted is already true.
        pass
    except psutil.AccessDenied:
        result = TerminationResult(
            TerminationOutcome.ACCESS_DENIED, pid, name, f'Access denied trying to end "{name}" (PID {pid}).'
        )
        _log_attempt(pid, name, result)
        return result

    result = TerminationResult(TerminationOutcome.SUCCESS, pid, name, f'"{name}" (PID {pid}) was ended successfully.')
    _log_attempt(pid, name, result)
    return result

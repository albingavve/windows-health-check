from unittest.mock import MagicMock, patch

import psutil
import pytest

from src.process_control import (
    PROTECTED_PROCESSES,
    TerminationOutcome,
    is_protected,
    terminate_process,
)


def _fake_process(name, terminate_side_effect=None, wait_side_effects=None, kill_side_effect=None):
    """A MagicMock standing in for psutil.Process(pid). `wait_side_effects`
    is consumed in order across successive .wait() calls (terminate's wait,
    then kill's wait if escalation happens)."""
    process = MagicMock()
    process.name.return_value = name
    if terminate_side_effect is not None:
        process.terminate.side_effect = terminate_side_effect
    if kill_side_effect is not None:
        process.kill.side_effect = kill_side_effect
    if wait_side_effects is not None:
        process.wait.side_effect = wait_side_effects
    return process


# --- protected list ---


@pytest.mark.parametrize("name", PROTECTED_PROCESSES)
def test_is_protected_matches_every_entry_in_the_list(name):
    assert is_protected(name) is True


@pytest.mark.parametrize("name", PROTECTED_PROCESSES)
def test_terminate_process_rejects_every_protected_entry_without_calling_terminate(name):
    fake_process = _fake_process(name)

    with patch("src.process_control.psutil.Process", return_value=fake_process), patch(
        "src.process_control._log_attempt"
    ):
        result = terminate_process(1234)

    assert result.outcome == TerminationOutcome.PROTECTED
    assert result.pid == 1234
    assert result.name == name
    fake_process.terminate.assert_not_called()
    fake_process.kill.assert_not_called()


def test_is_protected_is_case_insensitive():
    assert is_protected("SVCHOST.EXE") is True
    assert is_protected("svchost.exe") is True
    assert is_protected("SvcHost.Exe") is True
    assert is_protected("notreal.exe") is False


def test_terminate_process_rejects_protected_process_case_insensitively():
    fake_process = _fake_process("SVCHOST.EXE")

    with patch("src.process_control.psutil.Process", return_value=fake_process), patch(
        "src.process_control._log_attempt"
    ):
        result = terminate_process(4)

    assert result.outcome == TerminationOutcome.PROTECTED
    fake_process.terminate.assert_not_called()


# --- graceful termination ---


def test_terminate_process_succeeds_gracefully():
    fake_process = _fake_process("notepad.exe", wait_side_effects=[0])  # exits cleanly after terminate()

    with patch("src.process_control.psutil.Process", return_value=fake_process), patch(
        "src.process_control._log_attempt"
    ):
        result = terminate_process(500)

    assert result.outcome == TerminationOutcome.SUCCESS
    assert result.pid == 500
    assert result.name == "notepad.exe"
    fake_process.terminate.assert_called_once()
    fake_process.kill.assert_not_called()


# --- forceful fallback ---


def test_terminate_process_escalates_to_kill_after_graceful_timeout():
    fake_process = _fake_process(
        "stuckapp.exe",
        wait_side_effects=[psutil.TimeoutExpired(seconds=3), 0],  # graceful wait times out, kill's wait succeeds
    )

    with patch("src.process_control.psutil.Process", return_value=fake_process), patch(
        "src.process_control._log_attempt"
    ):
        result = terminate_process(501)

    assert result.outcome == TerminationOutcome.SUCCESS
    fake_process.terminate.assert_called_once()
    fake_process.kill.assert_called_once()


def test_terminate_process_reports_timeout_when_kill_also_fails_to_finish():
    fake_process = _fake_process(
        "zombie.exe",
        wait_side_effects=[psutil.TimeoutExpired(seconds=3), psutil.TimeoutExpired(seconds=2)],
    )

    with patch("src.process_control.psutil.Process", return_value=fake_process), patch(
        "src.process_control._log_attempt"
    ):
        result = terminate_process(502)

    assert result.outcome == TerminationOutcome.TIMEOUT
    fake_process.terminate.assert_called_once()
    fake_process.kill.assert_called_once()


# --- access denied ---


def test_terminate_process_handles_access_denied_on_lookup():
    with patch("src.process_control.psutil.Process", side_effect=psutil.AccessDenied(pid=999)), patch(
        "src.process_control._log_attempt"
    ):
        result = terminate_process(999)

    assert result.outcome == TerminationOutcome.ACCESS_DENIED
    assert result.pid == 999
    assert result.name is None


def test_terminate_process_handles_access_denied_on_terminate_call():
    fake_process = _fake_process("protected_by_os.exe", terminate_side_effect=psutil.AccessDenied(pid=42))

    with patch("src.process_control.psutil.Process", return_value=fake_process), patch(
        "src.process_control._log_attempt"
    ):
        result = terminate_process(42)

    assert result.outcome == TerminationOutcome.ACCESS_DENIED
    assert result.name == "protected_by_os.exe"


# --- not found ---


def test_terminate_process_handles_nonexistent_pid():
    with patch("src.process_control.psutil.Process", side_effect=psutil.NoSuchProcess(pid=99999)), patch(
        "src.process_control._log_attempt"
    ):
        result = terminate_process(99999)

    assert result.outcome == TerminationOutcome.NOT_FOUND
    assert result.pid == 99999


def test_terminate_process_treats_process_exiting_mid_attempt_as_success():
    # Exited on its own between our lookup and the terminate()/wait() call
    # — the caller's desired end state (process gone) is already true.
    fake_process = _fake_process("flaky.exe", terminate_side_effect=psutil.NoSuchProcess(pid=7))

    with patch("src.process_control.psutil.Process", return_value=fake_process), patch(
        "src.process_control._log_attempt"
    ):
        result = terminate_process(7)

    assert result.outcome == TerminationOutcome.SUCCESS


# --- logging ---


def test_terminate_process_logs_every_attempt(tmp_path):
    log_path = tmp_path / "process_actions.log"
    fake_process = _fake_process("notepad.exe", wait_side_effects=[0])

    with patch("src.process_control.psutil.Process", return_value=fake_process), patch(
        "src.process_control._LOG_PATH", log_path
    ):
        terminate_process(123)

    contents = log_path.read_text(encoding="utf-8")
    assert "pid=123" in contents
    assert "name=notepad.exe" in contents
    assert "outcome=success" in contents

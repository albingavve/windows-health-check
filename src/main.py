"""Entrypoint: starts the local dashboard server.

Run with: python -m src.main
"""

import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn
import win32api
import win32event
import winerror
from watchfiles import PythonFilter, run_process

# pythonw.exe (used for a no-console launch — see launch.vbs) leaves
# sys.stdout/sys.stderr as None rather than a real stream — confirmed, on
# this project's own dev machine, to crash uvicorn's own logging setup
# (`sys.stdout.isatty()` in uvicorn/logging.py) before the server even
# binds its port, taking down the plain print() call in main() below the
# same way. This patch runs at import time rather than inside main()/
# _serve() individually specifically so it also reaches the
# multiprocessing-spawned reload worker further down: that child process
# re-imports this module fresh and starts with its own None streams,
# independent of anything the parent process already patched. Redirecting
# to os.devnull gives every writer a real, harmless file object instead —
# output that has nowhere useful to go anyway (no console to show it) is
# simply discarded rather than crashing the whole process. A no-op under
# a normal terminal session, where these are already real streams.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

_HOST = "127.0.0.1"
_PORT = 8000
_DASHBOARD_URL = f"http://{_HOST}:{_PORT}"

# "Global\\" (rather than "Local\\") so this is enforced session-wide, not
# just within the current login session — matches how this single-user
# desktop tool is actually used. Kept alive for the whole process lifetime
# in this module-level variable: pywin32's PyHANDLE closes the underlying
# handle (releasing the mutex) as soon as it's garbage-collected, so a
# local variable here would let a second instance slip in as soon as
# main() returned.
_SINGLE_INSTANCE_MUTEX_NAME = "Global\\PCHealthDashboard_SingleInstance"
_singleton_mutex_handle = None


def _serve() -> None:
    uvicorn.run("src.api.server:app", host=_HOST, port=_PORT, reload=False)


def _port_already_bound() -> bool:
    """Secondary safety net alongside the named mutex below: if something
    is already listening on the dashboard's own host:port, treat that as
    "already running" too, even if the mutex check didn't catch it — e.g.
    a stale mutex left behind by a previous instance that didn't exit
    cleanly (Windows only guarantees a mutex is released on process exit,
    clean or not, but a genuinely wedged process could still be holding
    the port without having released anything yet)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((_HOST, _PORT))
    except OSError:
        return True
    finally:
        probe.close()
    return False


def _another_instance_already_running() -> bool:
    """True if another PC Health Dashboard instance is already running,
    per the named mutex (primary check) or the port-bind fallback
    (secondary check) above."""
    global _singleton_mutex_handle
    _singleton_mutex_handle = win32event.CreateMutex(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return True
    return _port_already_bound()


def _is_launcher_invocation() -> bool:
    """True when running under pythonw.exe — launch.vbs's no-console
    launch path — as opposed to a plain terminal `python -m src.main`
    session."""
    return os.path.basename(sys.executable).lower() == "pythonw.exe"


# Generous ceiling for _wait_for_server_then_open_browser below — normal
# startup (including the reload wrapper's own spin-up) has been well under
# this on this machine, but a slow/cold-cache first run shouldn't be cut
# off prematurely.
_SERVER_READY_MAX_WAIT_SECONDS = 20.0


def _wait_for_server_then_open_browser() -> None:
    """Poll the dashboard's own port until it accepts a connection (or the
    ceiling above elapses regardless), then open the browser. Runs on a
    background thread — started fire-and-forget from main() below — since
    the reload loop on the main thread blocks for the whole life of the
    process and can't be used to sequence this."""
    deadline = time.monotonic() + _SERVER_READY_MAX_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((_HOST, _PORT), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    webbrowser.open(_DASHBOARD_URL)


def main() -> None:
    if _another_instance_already_running():
        print("PC Health Dashboard is already running — opening it in your browser instead.")
        webbrowser.open(_DASHBOARD_URL)
        return

    if _is_launcher_invocation():
        # Only the no-console launcher path auto-opens a browser on a
        # fresh start — a plain terminal `python -m src.main` (the normal
        # dev workflow) doesn't and shouldn't, since that would pop open a
        # new tab every time a developer restarts the dev server. This is
        # also why launch.vbs no longer opens the browser itself: it used
        # to, unconditionally, on top of whatever main() did — the two
        # combined meant a launch while the dashboard was already running
        # opened two tabs (this branch's browser-open above, *and*
        # launch.vbs's own). Centralizing all browser-opening here, in the
        # one place that actually knows which case just happened, fixes
        # that without launch.vbs needing to duplicate any of this
        # module's detection logic.
        threading.Thread(target=_wait_for_server_then_open_browser, daemon=True).start()

    # Not using uvicorn's own reload=True: on this machine its Windows
    # restart path (src/...BaseReload.restart in uvicorn) sends a
    # CTRL_C_EVENT to the worker and then waits for it to exit with no
    # timeout or fallback. That wait can hang indefinitely — confirmed with
    # a minimal FastAPI app with none of this project's code involved — so
    # the very first edit after startup freezes the reloader forever and
    # silently no-ops every edit after that, exactly what's been happening.
    # watchfiles.run_process() does the same restart-on-change job but
    # escalates to a hard kill (TerminateProcess on Windows, via
    # multiprocessing) if the process doesn't exit within a few seconds,
    # which is what actually makes reload complete reliably here. Its
    # PythonFilter also ignores .git/__pycache__/.pytest_cache/etc. by
    # default and — unlike watching all of "src" unfiltered — won't
    # restart the whole process for a frontend-only edit under src/web/,
    # since only .py/.pyx/.pyd changes matter for a running Python process.
    run_process("src", target=_serve, watch_filter=PythonFilter())


if __name__ == "__main__":
    main()

"""Entrypoint: starts the local dashboard server.

Run with: python -m src.main
"""

import uvicorn
from watchfiles import PythonFilter, run_process


def _serve() -> None:
    uvicorn.run("src.api.server:app", host="127.0.0.1", port=8000, reload=False)


def main() -> None:
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

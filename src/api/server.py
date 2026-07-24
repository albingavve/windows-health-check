"""FastAPI app. Routes are kept thin: call a collector, shape the response."""

import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.collectors.diagnostics import diagnose_system
from src.collectors.process_list import ProcessGroup, get_process_list, group_processes
from src.collectors.startup_audit import get_startup_items
from src.collectors.system_stats import SystemSnapshot, get_system_snapshot

app = FastAPI(title="PC Health Dashboard")

# The frontend polls /api/stats, /api/processes, and /api/diagnostics on the
# same ~2s interval. Diagnostics is pure analysis over the other two
# collectors' output (see diagnostics.py), so without this cache every
# diagnostics poll would silently double the cost of process enumeration
# (~1s for ~285 processes) and the CPU snapshot's blocking read — exactly
# the kind of self-inflicted polling overhead CLAUDE.md warns against for a
# PC-health tool. A cache slightly shorter than the poll interval means
# whichever endpoint is hit first each cycle pays for a fresh reading and
# the others reuse it.
_CACHE_TTL_SECONDS = 1.8

_stats_cache: SystemSnapshot | None = None
_stats_cache_at: float = 0.0
_groups_cache: list[ProcessGroup] = []
_groups_cache_at: float = 0.0


def _get_cached_stats() -> SystemSnapshot:
    global _stats_cache, _stats_cache_at
    now = time.monotonic()
    if _stats_cache is None or now - _stats_cache_at > _CACHE_TTL_SECONDS:
        _stats_cache = get_system_snapshot()
        _stats_cache_at = now
    return _stats_cache


def _get_cached_groups() -> list[ProcessGroup]:
    global _groups_cache, _groups_cache_at
    now = time.monotonic()
    if now - _groups_cache_at > _CACHE_TTL_SECONDS:
        _groups_cache = group_processes(get_process_list())
        _groups_cache_at = now
    return _groups_cache


WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.middleware("http")
async def no_cache_static_assets(request: Request, call_next):
    """Force the browser to revalidate /assets on every request.

    This is a local dev tool with no build step or cache-busting filenames,
    so without this a stale cached app.js/index.html can keep running after
    an edit even through a hard refresh.
    """
    response = await call_next(request)
    if request.url.path.startswith("/assets") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/stats")
def read_stats() -> dict:
    """Current point-in-time system stats."""
    return _get_cached_stats().to_dict()


@app.get("/api/startup")
def read_startup() -> list[dict]:
    """Discovered startup items from the Startup folder and registry Run/RunOnce keys."""
    return [item.to_dict() for item in get_startup_items()]


@app.get("/api/processes")
def read_processes() -> list[dict]:
    """Running processes grouped by parent-child ancestry (falling back to
    shared executable name), each with summed CPU%/memory and its member
    processes for expansion — see process_list.group_processes()."""
    return [group.to_dict() for group in _get_cached_groups()]


@app.get("/api/diagnostics")
def read_diagnostics() -> list[dict]:
    """Rules-based "why is it slow" findings over the current stats/process
    data — see diagnostics.diagnose_system(). Empty list means nothing
    crossed a threshold, not that the check failed."""
    return [diagnosis.to_dict() for diagnosis in diagnose_system(_get_cached_stats(), _get_cached_groups())]


# Serve the frontend. Mounted after the API routes so /api/* takes priority.
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/")
def read_index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")

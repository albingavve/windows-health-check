"""FastAPI app. Routes are kept thin: call a collector, shape the response."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.collectors.system_stats import get_system_snapshot

app = FastAPI(title="PC Health Dashboard")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/api/stats")
def read_stats() -> dict:
    """Current point-in-time system stats."""
    snapshot = get_system_snapshot()
    return snapshot.to_dict()


# Serve the frontend. Mounted after the API routes so /api/* takes priority.
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/")
def read_index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")

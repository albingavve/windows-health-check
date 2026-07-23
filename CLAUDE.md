# CLAUDE.md — Project Brief for Claude Code

## What this is
A Windows 11 PC health & optimization tool. It analyzes a system's resource use,
startup programs, and background services, then gives the user clear, actionable
suggestions for improving performance — without touching Linux, without being a
"just switch OS" pitch, and without silently modifying anything.

**Working title:** PC Health Dashboard

## Goal (in priority order)
1. Show live system stats (CPU, RAM, disk, network) in a clean local dashboard.
2. Audit startup programs and background services, explain what each one does,
   and estimate its impact (boot time / memory / CPU).
3. Score overall "optimization health" and generate a short report with concrete
   suggestions the user can choose to act on.
4. (Stretch) Disk space treemap visualizer. (Stretch) before/after benchmark.

This is a **portfolio project** — code quality, clear structure, and a good README
matter as much as raw functionality. Build it like something you'd actually want
to link on LinkedIn.

## Tech stack
- **Language:** Python 3.11+
- **System data:** `psutil` for cross-platform stats; `pywin32` / `wmi` for
  Windows-specific data (services, startup registry keys, Task Scheduler).
- **Backend:** FastAPI, serving both a small JSON API and the static frontend.
- **Frontend:** plain HTML/CSS/JS + Chart.js (via CDN) for live charts. No frontend
  build step — keep this simple to run and simple to demo.
- **Storage:** SQLite (via `sqlite3` stdlib or `sqlmodel` if it simplifies things)
  for historical snapshots, once we get to the "score over time" feature.
- **Tests:** `pytest`. Collectors should be unit-testable independent of the API/UI.

## Non-negotiable safety rules
- **Read-only by default.** Nothing in this codebase should delete files, modify
  the registry, disable services, or uninstall software without an explicit,
  separate "apply" action that the user triggers — and even then, log what
  changed and make it easy to undo.
- Never claim a suggestion is 100% safe. Phrase things as recommendations with
  the reasoning shown, not commands.
- No telemetry, no phoning home, no bundled third-party analytics. Everything
  runs and stays local.

## Code conventions
- Type hints on all function signatures.
- Docstrings on public functions/classes (one-line summary is fine for small ones).
- Collectors (things that gather system data) live in `src/collectors/` and
  return plain dataclasses/dicts — no printing, no UI logic inside them.
- API routes in `src/api/` should be thin: call a collector, shape the response,
  return it. Business logic doesn't belong in route handlers.
- Prefer small, composable functions over large ones.
- Keep the frontend dependency-free beyond Chart.js from CDN — no npm build step
  for v1.

## Folder structure
```
pc-health-dashboard/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── src/
│   ├── main.py              # entrypoint: starts the FastAPI server
│   ├── collectors/          # system data gathering, no UI/API concerns
│   │   ├── system_stats.py  # CPU/RAM/disk/network via psutil
│   │   └── startup_audit.py # startup programs/services (Windows-specific)
│   ├── api/
│   │   └── server.py        # FastAPI app + routes
│   └── web/                 # static frontend (HTML/CSS/JS)
└── tests/
```

## Current status
Skeleton only. `system_stats.py` has a working basic implementation.
`startup_audit.py` is a stub — this is the next thing to build out.

## Roadmap (rough order of work)
1. Flesh out `system_stats.py` collector + `/api/stats` endpoint + live chart on
   the frontend polling every 1–2s.
2. Build `startup_audit.py`: read Startup folder, `Run`/`RunOnce` registry keys,
   and enumerate services via `pywin32`/`wmi`. Return structured results.
3. Add a simple "known bloatware/telemetry" lookup table (start small, expand
   over time) so audit results include plain-English explanations.
4. Compute an overall optimization score from the above.
5. Persist snapshots to SQLite; add a trend chart.
6. Stretch: disk treemap, benchmark comparison.

## How to run
```
pip install -r requirements.txt
python -m src.main
```
Then open http://localhost:8000 in a browser.

## Notes for Claude Code
- When adding a new collector, add a matching test in `tests/` using mocked
  `psutil`/`wmi` calls — don't require actual system access for tests to pass.
- If a feature needs elevated (admin) privileges, say so clearly in code
  comments and handle the permission-denied case gracefully instead of crashing.
- Ask before adding new third-party dependencies beyond what's already in
  `requirements.txt` — keep the dependency footprint deliberate.

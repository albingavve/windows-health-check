# PC Health Dashboard

A local, Windows 11-focused tool that analyzes your system's resource use,
startup programs, and background services — then shows you clear, actionable
ways to make it run better. Read-only by design: it recommends, it doesn't
touch anything without you telling it to.

## Status
🟢 Working v1 — live stats, full startup/service audit, and plain-English
explanations are all functional. Scheduled Tasks and historical tracking are
still on the roadmap.

## Features
- [x] Live CPU / RAM / disk / network dashboard
- [x] Startup program audit — Startup folder + registry Run/RunOnce keys
- [x] Windows service audit (300+ services enumerated via WMI)
- [x] Known-software lookup — plain-English descriptions and impact ratings
      (low/medium/high) for common apps, launchers, cloud sync tools, and
      peripherals software. Unmatched/unknown software is left unlabeled
      rather than guessed at.
- [x] Live search — filters by name, source, command, *and* description
- [ ] Optimization score
- [ ] Historical trend tracking
- [ ] Disk space treemap
- [ ] Before/after benchmark comparison
- [ ] Scheduled Tasks audit

## Screenshots
*(add a screenshot or two of the dashboard here — the startup audit table
with impact badges is a good one to show)*

## Getting started
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m src.main
```
Then open http://localhost:8000

## How it works
- **`src/collectors/system_stats.py`** — pulls live CPU/RAM/disk/network
  stats via `psutil`.
- **`src/collectors/startup_audit.py`** — scans the Startup folder, registry
  `Run`/`RunOnce` keys (via `winreg`), and Windows services (via `wmi`), then
  runs each result through a known-software lookup to attach a description
  and impact rating where available.
- **`src/collectors/known_software.py`** — a lookup table of common
  chat/gaming/cloud-sync/dev-tool software, matched case-insensitively
  against name and command. Deliberately conservative: unrecognized
  software is left blank rather than given a fabricated description.
- **`src/api/server.py`** — a thin FastAPI layer exposing `/api/stats` and
  `/api/startup`, plus serving the static frontend.
- **`src/web/`** — a dependency-light frontend (HTML/CSS/vanilla JS +
  Chart.js) polling `/api/stats` for live charts and fetching `/api/startup`
  once for the searchable audit table.

## Tech
Python, FastAPI, psutil, pywin32, WMI, Chart.js.

## Why
Windows 11 ships with a fair amount of bloatware and background noise, and
it's often not obvious what's safe to change or what a given startup entry
even is. This project makes that visible and understandable — without
requiring a switch to Linux, and without silently changing anything on your
system.

## Safety
Everything here is read-only analysis. Nothing is deleted, disabled, or
modified automatically — the tool surfaces information; you decide what to
do with it.
# CLAUDE.md — Project Brief for Claude Code

## What this is
A Windows 11 PC health & optimization tool that's grown into a genuine
**Task Manager replacement/companion**: live system stats, a full sortable
process list with real CPU/memory usage, and a startup/service audit that
explains what's running and why, all in one dashboard the user actually
wants to use day-to-day instead of opening Task Manager.

**Working title:** PC Health Dashboard

## Mission (read this before making feature decisions)
The user likes Windows 11 and wants to stay on it — this project is their
answer to "just switch to Linux," not a step toward leaving Windows. The
point is to make Windows itself transparent and controllable enough that
switching operating systems stops being the only way to feel in control of
your own machine.

Concretely, that means every feature should serve one of these:
1. **Show what the PC is actually doing behind the screen** — not just raw
   numbers, but the real structure (e.g. "one YouTube tab" is actually 11
   browser processes, here's why memory looks full).
2. **Explain *why*** — not just "CPU is at 40%," but "here's what's
   consuming it and what that means." Task Manager shows data; this tool
   should show understanding.
3. **Give the user real control** — clear, safe, reversible ways to act on
   what they've learned (disable a startup item, stop a background
   service), not just a read-only report.
4. **Suggest concrete optimizations** — proactive, specific, and honest
   about tradeoffs, not vague "clean your PC!" advice.

When a feature could go in a "flashier but shallower" direction or a
"less flashy but genuinely explains the machine" direction, prefer the
latter — that's the actual value proposition of this whole project.

## Goal (in priority order)
1. ~~Show live system stats (CPU, RAM, disk, network) in a clean local
   dashboard.~~ **Done.**
2. ~~Audit startup programs and background services, explain what each one
   does, and estimate its impact.~~ **Done.**
3. **Full live process list**, sortable by CPU%, memory, name, etc. — this
   is the current focus. The goal is real day-to-day usability as a Task
   Manager alternative, not a one-off demo table.
4. Correlate startup/service audit entries with their live running process
   (if any) so the audit table also shows real-time CPU/memory, not just
   the static impact estimate.
5. Score overall "optimization health" and generate a short report with
   concrete suggestions the user can choose to act on.
6. (Stretch) Historical trend tracking. (Stretch) Disk space treemap.
   (Stretch) Scheduled Tasks audit. (Stretch, needs explicit sign-off before
   building — see safety rules) Process termination ("End Task").

This is a **portfolio project**, but it has also become the person's actual
daily driver for checking resource usage — treat real-world usability,
performance of the live views, and data accuracy as seriously as you would
code quality and structure.

## Tech stack
- **Language:** Python 3.11+
- **System data:** `psutil` for cross-platform stats and process
  enumeration; `pywin32` / `wmi` for Windows-specific data (services,
  startup registry keys, Task Scheduler).
- **Backend:** FastAPI, serving both JSON APIs and the static frontend.
- **Frontend:** plain HTML/CSS/JS + Chart.js (via CDN). No frontend build
  step — keep this simple to run and simple to demo. Visual theme is an
  intentional "cyberpunk exposed-mechanism" identity (gunmetal/chrome
  surfaces, cyan + magenta neon, gauge-dial stat displays, jeweled status
  dots for enabled/impact states, Orbitron/Rajdhani display font + monospace
  for data). Keep new UI consistent with this theme rather than reverting
  to generic dashboard styling.
- **Storage:** SQLite for historical snapshots, once we reach that feature.
- **Tests:** `pytest`. Collectors should be unit-testable independent of the
  API/UI — mock `psutil`/`wmi` rather than requiring real system access.

## Non-negotiable safety rules
- **Read-only by default.** Nothing in this codebase should delete files,
  modify the registry, disable services, uninstall software, or **terminate
  a running process** without an explicit, separate "apply" action the user
  triggers — and even then, log what changed and make it easy to undo.
  Process termination ("End Task") is *not yet in scope* — do not add it
  unless the user explicitly asks for it in a future prompt, since it's a
  meaningfully higher-risk action than anything built so far.
- Never claim a suggestion is 100% safe. Phrase things as recommendations
  with the reasoning shown, not commands.
- No telemetry, no phoning home, no bundled third-party analytics.
  Everything runs and stays local.
- Since this is now used as a real day-to-day tool, don't let live polling
  (process list, stats) become a resource hog itself — that would be an
  ironic failure for a PC-health tool. Be deliberate about polling
  intervals and avoid re-enumerating more than necessary.

## Code conventions
- Type hints on all function signatures.
- Docstrings on public functions/classes (one-line summary is fine for
  small ones).
- Collectors (things that gather system data) live in `src/collectors/` and
  return plain dataclasses/dicts — no printing, no UI logic inside them.
- API routes in `src/api/` should be thin: call a collector, shape the
  response, return it. Business logic doesn't belong in route handlers.
- Prefer small, composable functions over large ones.
- Keep the frontend dependency-free beyond Chart.js from CDN — no npm
  build step.

## Folder structure
```
pc-health-dashboard/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── src/
│   ├── main.py                # entrypoint: starts the FastAPI server
│   ├── collectors/            # system data gathering, no UI/API concerns
│   │   ├── system_stats.py    # CPU/RAM/disk/network via psutil
│   │   ├── startup_audit.py   # startup programs/services (Windows-specific)
│   │   ├── known_software.py  # bloatware/telemetry lookup + descriptions
│   │   └── process_list.py    # full running-process enumeration + live
│   │                          # CPU/memory usage (new — powers both the
│   │                          # process manager view and startup-item
│   │                          # usage correlation)
│   ├── api/
│   │   └── server.py          # FastAPI app + routes
│   └── web/                   # static frontend (HTML/CSS/JS)
└── tests/
```

## Current status
Live stats, full startup/service audit with known-software lookup, search,
the cyberpunk theme pass, the live process list (grouped by app, ~1s
response for ~285 processes), and process grouping/tree view are all
working and verified in-browser. Column sorting for the Process Manager
table has *not* been built yet — deferred until explicitly requested.
Next up: correlating startup/service audit entries with live process data.

## Roadmap (rough order of work)
1. ~~System stats collector + endpoint + live gauge dials on frontend.~~ Done.
2. ~~Startup/service audit (registry, startup folder, services via wmi).~~ Done.
3. ~~Known-software lookup table for plain-English descriptions/impact.~~ Done.
4. ~~Cyberpunk visual theme.~~ Done.
5. ~~Full process list collector + `/api/processes` endpoint + Process
   Manager view.~~ Done. Response time optimized (~1s for ~285 processes,
   accepted as the practical floor for a psutil-based approach — a raw
   `NtQuerySystemInformation`/`ctypes` rewrite was considered and
   deliberately deferred, not needed for current goals).
6. ~~Process grouping / tree view~~ Done. `group_processes()` clusters by
   parent-child ancestry where child/parent share an executable name
   (catches browser-style renderer/GPU/utility trees), falling back to
   grouping same-named processes with no such link (catches svchost.exe-
   style cases where many unrelated processes share a generic supervisor
   parent). `/api/processes` returns groups with summed CPU/memory and
   member processes; the Process Manager table renders these as
   collapsed-by-default expandable rows. Verified live: correctly
   identified the user's own Firefox session as one 16-process/~4.5GB
   group and VS Code as 18 processes, with 90+ unrelated svchost.exe hosts
   correctly kept in the honest "(Group)" fallback bucket rather than
   implied to be one app.
7. **Correlate startup/service audit items with live process data (current
   focus)** — reuse
   the process-list data to show real-time CPU/memory next to each
   startup/service entry, not just its static impact estimate.
8. **"Why is it slow" diagnostic engine** — rules-based analysis over live
   stats + process data producing plain-English diagnoses (e.g. disk-bound
   vs. memory-bound vs. CPU-bound bottleneck signatures).
9. **Top offenders leaderboard** — top CPU/memory consumers sampled over a
   rolling window (not just instantaneous), since instantaneous CPU% is
   noisy.
10. **Broader background-noise classification** — extend
    `known_software.py`'s concept to categorize *all* running processes
    (OS-critical / user app / browser-renderer / background-updater /
    telemetry), not just startup items.
11. **Bloatware/service management (action layer)** — safe, reversible
    controls (disable/enable only, not uninstall/delete) for startup items
    and user-installed services, with confirmation previews and a change
    log. Scope to items the known-software lookup recognizes first, not
    arbitrary system services. This should come after the diagnostic/
    classification work above, since it's most valuable once the tool can
    clearly explain *why* something is worth disabling.
12. Optimization score + report, synthesizing the diagnostic engine's
    findings into an overall picture.
13. Stretch: historical trend tracking, disk treemap, Scheduled Tasks audit.

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
  comments and handle the permission-denied case gracefully instead of
  crashing.
- Ask before adding new third-party dependencies beyond what's already in
  `requirements.txt` — keep the dependency footprint deliberate.
- `psutil.Process.cpu_percent()` returns 0/garbage on its first call for a
  given process — it needs a prior "priming" call before the value is
  meaningful. Handle this properly (e.g. a persistent process cache across
  polls) rather than reporting misleading first-read numbers.
- Since this now needs to hold up as a real daily-use tool, prefer
  correctness and stable performance over cleverness — e.g. avoid
  re-creating `psutil.Process` objects every single poll if a cached
  approach is more efficient, and profile if a feature feels sluggish
  rather than assuming it's fine.
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
3. ~~Full live process list, sortable, with real day-to-day usability as a
   Task Manager alternative.~~ **Done.**
4. ~~Process grouping/tree view + process role labeling, so a browser or
   editor's many child processes read as one coherent app instead of
   anonymous rows.~~ **Done.**
5. ~~"Why is it slow" diagnostic engine.~~ **Done.**
6. ~~Process termination ("End Task"), with a hardcoded protected-process
   list and confirmation flow.~~ **Done.**
7. Score overall "optimization health" and generate a short report with
   concrete suggestions the user can choose to act on. **Not yet built.**
8. (Stretch) Historical trend tracking. (Stretch) Disk space treemap.
   (Stretch) Scheduled Tasks audit. (Future, needs explicit scoping
   discussion first — see safety rules) Bloatware/service management
   (disable/enable, not uninstall).

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
  modify the registry, disable services, or uninstall software without an
  explicit, separate "apply" action the user triggers — and even then, log
  what changed and make it easy to undo.
- **Process termination ("End Task") is now in scope, explicitly requested
  by the user, with strict guardrails:**
  - Maintain a hardcoded, conservative list of protected system processes
    (e.g. System, System Idle Process, csrss.exe, wininit.exe,
    services.exe, lsass.exe, smss.exe, winlogon.exe) that cannot be
    terminated through the app under any circumstances — not just warned
    about, actually blocked.
  - Only individual processes can be terminated, never a collapsed
    group row — the user must be looking at the specific PID being acted
    on.
  - Always require explicit confirmation showing exactly what will be
    terminated (name, PID, memory) before acting.
  - Attempt graceful termination first, fall back to forceful kill only
    after a short timeout if the process doesn't respond.
  - Log every termination attempt (what, when, outcome) — this is the
    first destructive action in the app, so this is the first place the
    existing "log what changed" rule actually needs to be implemented.
  - Handle permission errors gracefully (many processes need elevated
    rights to terminate) — never crash, always explain clearly.
  - Still out of scope, not requested: uninstalling software, deleting
    files, modifying the registry, disabling services. Do not add these
    unless separately, explicitly requested.
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
│   │   ├── startup_audit.py   # startup/service audit; orphan detection;
│   │   │                      # true StartupApproved enabled state
│   │   ├── known_software.py  # bloatware/telemetry lookup + descriptions
│   │   ├── process_list.py    # process enumeration, grouping (union-find),
│   │   │                      # role labeling via cmdline parsing, live
│   │   │                      # CPU/memory usage
│   │   ├── process_control.py # process termination: protected-process
│   │   │                      # list, graceful->forceful terminate, logging
│   │   ├── diagnostics.py     # rules-based "why is it slow" signatures
│   │   │                      # (cpu_dominance, memory_pressure, disk_bound)
│   │   └── system_specs.py    # static hardware/OS specs (CPU, RAM, GPU,
│   │                          # storage, motherboard) via wmi, cached once
│   ├── api/
│   │   └── server.py          # FastAPI app + routes
│   └── web/                   # static frontend (HTML/CSS/JS)
└── tests/
```

## Current status
Feature-complete v1+ and verified in-browser on the user's real machine
throughout. Working: live stats (gauge dials), full startup/service audit
(known-software lookup, orphan detection, true StartupApproved enabled
state, search, sort), Process Manager (grouping/tree view, role labeling,
search, sort), a collapsible Diagnostics popup ("why is it slow"), a
collapsible Specs popup (static hardware info), resizable panels, and
process termination ("End Task") with a hardcoded protected-process list.
A Devices popup (connected USB peripherals, keyboards, monitors — built-in
vs. external) rounds out the hardware picture alongside Specs. Single-
instance enforcement (a named Windows mutex in `src/main.py`, with a
port-bind fallback check) plus a `launch.vbs` one-click launcher — see
"How to run" below — mean the dashboard no longer requires a terminal for
day-to-day use. Cyberpunk visual theme applied throughout. Security/privacy
audit of the repo has been done (no personal data leaked in code, history,
or fixtures — see git history for details if unsure).

**Not yet built:** optimization score/report, top-offenders leaderboard,
historical trend tracking, disk treemap, Scheduled Tasks audit, bloatware/
service disable-enable management, correlating startup/service items with
their live process data.

## Roadmap (rough order of work)
1. ~~System stats collector + endpoint + live gauge dials.~~ Done.
2. ~~Startup/service audit (registry, startup folder, services via wmi).~~ Done.
3. ~~Known-software lookup table for plain-English descriptions/impact.~~ Done.
4. ~~Cyberpunk visual theme.~~ Done.
5. ~~Full process list collector + `/api/processes` + Process Manager
   view.~~ Done. (~1s response for ~285 processes accepted as the
   practical floor for a psutil-based approach; a raw
   `NtQuerySystemInformation`/`ctypes` rewrite was considered and
   deliberately deferred.)
6. ~~Process grouping/tree view (union-find on parent-child + shared-name
   fallback) + process role labeling via cmdline parsing.~~ Done. This
   directly answers "why is memory full when I only have one YouTube tab
   open."
7. ~~Sortable columns + search on both Process Manager and Startup &
   Services Audit (feature parity between the two).~~ Done.
8. ~~"Why is it slow" diagnostic engine — cpu_dominance, memory_pressure,
   disk_bound signatures, collapsible popup UI.~~ Done.
9. ~~Orphaned startup-entry detection + true StartupApproved-based enabled
   state (fixes Task Manager-disabled items showing as "Enabled").~~ Done.
10. ~~Specs popup (CPU/RAM/GPU/storage/motherboard/OS via wmi, cached
    once).~~ Done.
11. ~~Resizable panels + layout reorder (Process Manager before Startup
    Audit) + collapsible Diagnostics/Specs pills instead of a persistent
    banner.~~ Done.
12. ~~Process termination ("End Task") — hardcoded protected-process list,
    individual-process-only, confirm dialog, graceful->forceful, logged.~~
    Done.
13. **Correlate startup/service audit items with live process data** —
    reuse Process Manager's data to show real-time CPU/memory next to each
    startup/service entry, not just its static impact estimate. Not yet
    built, still a real gap.
14. **Top offenders leaderboard** — top CPU/memory consumers sampled over
    a rolling window, not just instantaneous.
15. **Broader background-noise classification** — extend
    `known_software.py`'s concept to categorize *all* running processes
    (OS-critical / user app / browser-renderer / background-updater /
    telemetry), not just startup items.
16. **Bloatware/service management (action layer)** — safe, reversible
    disable/enable controls for startup items and user-installed services,
    with confirmation previews and a change log. Needs its own scoping
    discussion before building (similar to how End Task was scoped) —
    don't build without that discussion happening first.
17. Optimization score + report, synthesizing the diagnostic engine's
    findings into an overall picture.
18. ~~Single-instance enforcement (named Windows mutex + port-bind
    fallback in `src/main.py`) + `launch.vbs` one-click launcher
    (background start via `pythonw.exe`, then opens the default
    browser).~~ Done. Resolves the previously-undecided "how to launch
    without a terminal" question — see README's "One-click launch"
    section.
19. Stretch: historical trend tracking, disk treemap, Scheduled Tasks
    audit.

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

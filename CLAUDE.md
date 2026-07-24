# CLAUDE.md — Project Brief for Claude Code

## What this is
A Windows 11 PC health & optimization tool that replaced Task Manager for
daily use: live system stats, a full process manager with grouping and
process termination, a startup/service audit that explains what's running
and why, plus diagnostics, specs, and devices panels — all built to make
Windows itself transparent and controllable.

**Working title:** PC Health Dashboard
**Status: v1 complete.** This file describes the current, real state of the
project — not a plan for something not yet built. Roadmap items below are
genuinely unbuilt v2 work, not aspirational.

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
   shows understanding.
3. **Give the user real control** — clear, safe, reversible ways to act on
   what they've learned, not just a read-only report.
4. **Suggest concrete optimizations** — proactive, specific, and honest
   about tradeoffs, not vague "clean your PC!" advice.

When a feature could go in a "flashier but shallower" direction or a
"less flashy but genuinely explains the machine" direction, prefer the
latter. When data can't be determined reliably (USB port type, exact
browser tab identity, webcam built-in status, CPU temperature without
elevation), say so honestly rather than guessing — this has been a
consistent, deliberate standard throughout the project and should continue.

## What's built (v1)

**Live overview**
- CPU/RAM/disk/network stats with gauge-dial UI (`system_stats.py`)
- Diagnostics popup: rules-based "why is it slow" signatures — cpu_dominance,
  memory_pressure, disk_bound — each naming the specific responsible
  process/group, with an empty state ("Nothing unusual detected") rather
  than always finding something to say (`diagnostics.py`)
- Specs popup: static hardware/OS info via wmi, queried once and cached
  (`system_specs.py`)
- Devices popup: USB peripherals, keyboards, displays, with built-in/
  external labeling, deduplication of multi-interface devices, and honest
  fallback for anything unrecognized (`device_inventory.py`,
  `known_devices.py`)

**Process Manager**
- Full process enumeration with live CPU%/memory (`process_list.py`)
- Grouping via union-find: real parent-child ancestry clusters (e.g.
  browser renderer/GPU/utility processes) vs. an honestly-labeled
  shared-name-only fallback bucket (e.g. `svchost.exe (Group)`) — never
  implies a false relationship
- Process role labeling via command-line parsing (GPU Process, Tab Content
  Process, Extension Host, etc.)
- Sortable columns, live search
- Process termination ("End Task"): hardcoded protected-process list
  (checked before any OS call is attempted), individual-process-only
  scope, confirmation dialog, graceful-then-forceful termination, local
  action logging (`process_control.py`)

**Startup & Services Audit**
- Registry Run/RunOnce, Startup folder, and services via wmi
  (`startup_audit.py`)
- Known-software lookup: plain-English descriptions + impact ratings,
  honest silence for unmatched software (`known_software.py`)
- Orphaned entry detection (registry entry exists but the target
  executable no longer does) — impact rating correctly suppressed for
  these, since a nonexistent program has no real resource cost
- True enabled/disabled state via the `StartupApproved` registry key
  (undocumented Windows internals, same caveat class as other
  low-level Windows behavior this project reads) — this is what Task
  Manager's own "Disable" button actually writes to; it does NOT remove
  the underlying Run key, which is why naive key-presence checks report
  the wrong state
- Sortable columns, live search (feature parity with Process Manager)

**Daily usability / release infra**
- Cyberpunk "exposed mechanism" visual theme throughout (gunmetal/chrome,
  cyan+magenta neon, gauge dials, jeweled status dots, Orbitron/Rajdhani +
  monospace)
- Resizable panels; Process Manager ordered before Startup Audit
- Single-instance enforcement via a named Windows mutex — accidental
  duplicate launches are a no-op, not a resource-competing second server
- `launch.vbs` one-click launcher (no console window, no terminal needed)
- MIT licensed, public-release README, security/privacy audit completed
  (no personal data in code, fixtures, or git history as of that audit —
  re-check if a long time has passed or significant new collectors have
  been added since)

## Tech stack
- **Language:** Python 3.11+
- **System data:** `psutil` (cross-platform stats, process enumeration);
  `pywin32`/`wmi` (Windows-specific: services, startup registry, devices,
  specs)
- **Backend:** FastAPI. Routes are thin — call a collector, shape the
  response, no business logic in route handlers.
- **Frontend:** plain HTML/CSS/JS + Chart.js via CDN. No build step.
- **Storage:** none yet (v2 historical tracking would introduce SQLite)
- **Tests:** `pytest`, mocking `psutil`/`wmi` — no real system access
  required to run the suite

## Non-negotiable safety rules
- **Read-only by default.** Nothing deletes files, modifies the registry,
  disables services, or uninstalls software without an explicit, separate
  "apply" action — and even then, log what changed and make it reversible.
- **Process termination is the one implemented exception, with strict,
  already-built guardrails — do not weaken these:**
  - Hardcoded protected-process list (see `process_control.py`), checked
    before any termination attempt, not relied on as a fallback after an
    OS-level refusal.
  - Individual processes only — never a collapsed group row.
  - Explicit confirmation showing name/PID/memory before acting.
  - Graceful termination attempted first, forceful kill only as a timed
    fallback.
  - Every attempt logged locally.
- **Future destructive actions (startup/service disable-enable,
  uninstall, file deletion) are still out of scope** until separately,
  explicitly requested and scoped the same deliberate way End Task was —
  do not add these speculatively.
- No telemetry, no phoning home, no third-party analytics. Fully local.
- Don't let live polling become a resource hog itself — that would be an
  ironic failure for a PC-health tool. Be deliberate about polling
  intervals; the Devices panel specifically does NOT poll continuously
  (fetch-on-open + manual refresh only) because its WMI queries are
  comparatively heavy.

## Known, accepted issues (don't re-litigate from scratch — read this first)
- **Devices panel occasional empty results under heavy concurrent load.**
  Root cause: WMI device queries contend with the 2s stats/process/
  diagnostics polling for thread pool availability. A real leak in timeout
  cleanup was found and fixed; the underlying contention is accepted for
  now. If this becomes a frequent practical problem, the real fix is
  likely isolating heavy WMI calls onto a dedicated worker rather than
  sharing FastAPI's default thread pool with the frequent-polling
  endpoints — don't re-chase the pythonw/COM theories already ruled out.
- **CPU% differs from Task Manager's number.** This is expected, not a
  bug — Task Manager (Win10+) uses a frequency-scaling-aware "CPU
  utility" metric; this project uses `psutil`'s standard raw busy-time
  metric. Documented in the README; not planned to be changed unless the
  user asks to specifically match Task Manager's methodology.
- **USB port type (A/C) is not reported.** Not available via standard
  Windows device APIs — deliberately omitted rather than guessed.
- **Webcam built-in status is best-effort only.** `LocationInformation`
  isn't consistently populated by all manufacturers; left blank when
  unreliable rather than assumed.

## Code conventions
- Type hints on all function signatures; docstrings on public functions/
  classes.
- Collectors (`src/collectors/`) return plain dataclasses/dicts, no
  printing, no UI logic.
- API routes thin; business logic lives in collectors.
- Mock `psutil`/`wmi` in tests rather than requiring real system access.
- Keep the frontend dependency-free beyond Chart.js — no npm build step.
- `psutil.Process.cpu_percent()` needs a priming call before it's
  meaningful — use a persistent process cache across polls, not fresh
  `Process` objects each time.
- Prefer correctness and stable performance over cleverness for anything
  polled live — this is a real daily-use tool now, not just a demo.

## Folder structure
```
pc-health-dashboard/
├── CLAUDE.md
├── README.md
├── LICENSE
├── requirements.txt
├── launch.vbs                 # one-click launcher, no console window
├── src/
│   ├── main.py                # entrypoint; single-instance mutex; starts uvicorn
│   ├── collectors/
│   │   ├── system_stats.py
│   │   ├── startup_audit.py
│   │   ├── known_software.py
│   │   ├── process_list.py
│   │   ├── process_control.py
│   │   ├── diagnostics.py
│   │   ├── system_specs.py
│   │   ├── device_inventory.py
│   │   └── known_devices.py
│   ├── api/
│   │   └── server.py
│   └── web/                   # HTML/CSS/JS, cyberpunk theme
└── tests/
```

## How to run
`launch.vbs` for normal use (see README). For development:
```
pip install -r requirements.txt
python -m src.main
```

## Roadmap (v2 — not yet built, ordered roughly by value)
1. **Correlate startup/service audit entries with live process data** —
   reuse Process Manager's data to show real-time CPU/memory next to each
   startup/service entry instead of just a static impact estimate. Highest-
   value remaining item; ties the two core tables together.
2. **Top offenders leaderboard** — top CPU/memory consumers over a rolling
   window, not just instantaneous.
3. **Broader background-noise classification** — extend
   `known_software.py`'s concept to categorize *all* running processes,
   not just startup items.
4. **Bloatware/service management (action layer)** — safe, reversible
   disable/enable for startup items and user-installed services. Needs its
   own explicit scoping discussion before building, same as End Task did —
   do not build without that conversation happening first.
5. **Optimization score/report** synthesizing the diagnostic engine's
   findings.
6. Stretch: historical trend tracking (would introduce SQLite), disk space
   treemap, Scheduled Tasks audit, optional CPU/GPU temperature (needs an
   explicit admin-elevation or vendor-SDK tradeoff decision first).

## Notes for Claude Code
- Before starting new work, check "Known, accepted issues" above — several
  theories have already been tried and ruled out; don't re-derive them
  from scratch.
- If a feature needs elevated (admin) privileges, say so clearly and
  handle the permission-denied case gracefully.
- Ask before adding new third-party dependencies.
- This project has a strong, established pattern: verify claims against
  the user's real machine (not just mocked tests) before declaring
  something fixed, and be honest in the summary about what was actually
  confirmed vs. assumed. Keep doing this — it's caught multiple real bugs
  that passing tests alone would have missed.

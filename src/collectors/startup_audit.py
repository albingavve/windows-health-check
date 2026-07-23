"""Audits startup programs and services on Windows.

STUB — this is the next module to build out with Claude Code.

Planned data sources:
- Startup folder(s): shell:startup and shell:common startup
- Registry Run/RunOnce keys (HKCU and HKLM, via `winreg`)
- Scheduled Tasks that run at logon (via `pywin32` or `schtasks` output)
- Running services and their startup type (via `wmi` or `pywin32`)

Each finding should map to a StartupItem so the API/UI layer doesn't need to
know where the data came from.
"""

from dataclasses import dataclass
from enum import Enum


class StartupSource(str, Enum):
    STARTUP_FOLDER = "startup_folder"
    REGISTRY_RUN = "registry_run"
    SCHEDULED_TASK = "scheduled_task"
    SERVICE = "service"


@dataclass
class StartupItem:
    name: str
    source: StartupSource
    command: str
    enabled: bool
    # Filled in once we have the bloatware/telemetry lookup table (roadmap step 3)
    known_description: str | None = None
    estimated_impact: str | None = None  # e.g. "low" / "medium" / "high"


def get_startup_items() -> list[StartupItem]:
    """Return all discovered startup items across all sources.

    TODO: implement each source. Suggested order:
    1. Startup folder (simplest — just a directory listing)
    2. Registry Run keys (winreg)
    3. Services (wmi or pywin32)
    4. Scheduled Tasks (more involved — schtasks or COM API)
    """
    raise NotImplementedError("startup_audit is a stub — build me next")

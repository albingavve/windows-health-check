"""Audits startup programs and services on Windows.

Implemented data sources:
- Startup folder(s): shell:startup and shell:common startup
- Registry Run/RunOnce keys (HKCU and HKLM, via `winreg`)
- Services and their startup type (via `wmi`)

Not yet implemented (planned next):
- Scheduled Tasks that run at logon (via `pywin32` or `schtasks` output)

Each finding maps to a StartupItem so the API/UI layer doesn't need to know
where the data came from.
"""

import os
import winreg
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

import pythoncom
import win32com.client
import wmi


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

    def to_dict(self) -> dict:
        return asdict(self)


# (hive, subkey) pairs to enumerate. HKLM entries apply to all users; HKCU to
# the current user only. RunOnce keys are frequently empty or absent.
_REGISTRY_RUN_KEYS = [
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
]


@contextmanager
def _com_initialized():
    """Ensure COM is initialized on the calling thread.

    FastAPI runs sync route handlers in a worker thread pool, and those
    threads don't have COM initialized by default — win32com/wmi calls fail
    with "CoInitialize has not been called" unless we do this per call.
    """
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def _resolve_shortcut(path: Path) -> str:
    """Resolve a .lnk file to its target path + arguments.

    Falls back to the raw .lnk path if COM resolution fails for any reason
    (e.g. a malformed shortcut).
    """
    try:
        with _com_initialized():
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(str(path))
            target = shortcut.Targetpath
            if not target:
                return str(path)
            return f"{target} {shortcut.Arguments}".strip()
    except Exception:
        return str(path)


def _scan_startup_folder(folder: Path) -> list[StartupItem]:
    """Return startup items found directly inside a single startup folder."""
    items: list[StartupItem] = []
    if not folder.is_dir():
        return items

    for entry in folder.iterdir():
        if not entry.is_file() or entry.name.lower() == "desktop.ini":
            continue

        command = _resolve_shortcut(entry) if entry.suffix.lower() == ".lnk" else str(entry)
        items.append(
            StartupItem(
                name=entry.stem,
                source=StartupSource.STARTUP_FOLDER,
                command=command,
                enabled=True,
            )
        )
    return items


def _scan_registry_run_keys() -> list[StartupItem]:
    """Return startup items from the registry Run/RunOnce keys (HKCU + HKLM)."""
    items: list[StartupItem] = []

    for hive, subkey in _REGISTRY_RUN_KEYS:
        try:
            key = winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ)
        except FileNotFoundError:
            continue

        with key:
            index = 0
            while True:
                try:
                    name, command, _value_type = winreg.EnumValue(key, index)
                except OSError:
                    break
                items.append(
                    StartupItem(
                        name=name,
                        source=StartupSource.REGISTRY_RUN,
                        command=command,
                        enabled=True,
                    )
                )
                index += 1

    return items


def _scan_services() -> list[StartupItem]:
    """Return startup items for every registered Windows service.

    `enabled` reflects the service's startup type (`StartMode == "Auto"`):
    services set to Manual/Disabled don't run automatically at boot, even
    though they're still registered.
    """
    try:
        with _com_initialized():
            connection = wmi.WMI()
            services = connection.Win32_Service()
            return [
                StartupItem(
                    name=service.DisplayName or service.Name,
                    source=StartupSource.SERVICE,
                    command=service.PathName or "",
                    enabled=service.StartMode == "Auto",
                )
                for service in services
            ]
    except Exception:
        # WMI can be unavailable (e.g. service disabled, COM init issues) —
        # degrade to no results rather than crashing the whole audit.
        return []


def get_startup_items() -> list[StartupItem]:
    """Return all discovered startup items across the implemented sources.

    TODO: add Scheduled Tasks source.
    """
    user_startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    common_startup = Path(os.environ["PROGRAMDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"

    return [
        *_scan_startup_folder(user_startup),
        *_scan_startup_folder(common_startup),
        *_scan_registry_run_keys(),
        *_scan_services(),
    ]

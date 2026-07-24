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

from src.collectors.known_software import lookup_known_software


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
    # True when the command's executable path was resolved and no longer
    # exists on disk — a leftover registry entry from an uninstalled
    # program. Only computed for registry Run/RunOnce entries so far (see
    # _is_orphaned()); always False for other sources.
    is_orphaned: bool = False
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


def _extract_executable_path(command: str) -> str | None:
    """Best-effort extraction of the executable path from a Run-key command
    string — handles a quoted path (`"C:\\...\\app.exe" --flag`) and a bare
    unquoted path followed by arguments (`C:\\...\\app.exe --flag`) alike.

    Returns None for a blank command; callers should skip the orphaned-path
    check entirely in that case rather than guess at a path.
    """
    command = command.strip()
    if not command:
        return None

    if command.startswith('"'):
        end_quote = command.find('"', 1)
        if end_quote != -1:
            return command[1:end_quote]
        return command[1:]  # unterminated quote — best effort on the rest

    return command.split(" ", 1)[0]


def _is_orphaned(command: str) -> bool:
    """Return True if `command`'s executable path was resolved and
    definitively does not exist on disk.

    Only absolute paths are checked. A bare filename (e.g. "rundll32.exe")
    could still resolve via the system PATH, and guessing wrong there would
    falsely flag a perfectly valid entry as orphaned — worse than not
    flagging it at all — so those are left unflagged rather than guessed at,
    matching known_software.py's "don't fabricate" approach.
    """
    path = _extract_executable_path(command)
    if not path:
        return False

    candidate = Path(os.path.expandvars(path))
    if not candidate.is_absolute():
        return False

    return not candidate.exists()


# StartupApproved's binary format is undocumented by Microsoft — this is
# community reverse-engineering (relied on by tools like Sysinternals
# Autoruns) rather than an official API, the same caveat as the
# NtQuerySystemInformation approach considered (and deferred) for
# process_list.py. Consistently observed across Windows 10/11: a 12-byte
# value per Run entry name, where the first byte is 0x02 or 0x06 when
# enabled, and 0x03 (followed by an 8-byte FILETIME of when it was
# disabled) when the user disabled it via Task Manager's Startup tab.
_STARTUP_APPROVED_ENABLED_FIRST_BYTES = {0x02, 0x06}
_STARTUP_APPROVED_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def _read_startup_approved_enabled(hive: int, name: str) -> bool | None:
    """Return the true enabled state for a Run-key entry per
    StartupApproved\\Run, or None if no override is recorded there.

    Task Manager's "Disable" button on the Startup tab doesn't remove the
    original Run value — it writes a suppression flag here instead, which
    is why `enabled` can't just mean "the Run key entry exists". An absent
    override means the entry has never been touched and is enabled by
    default.
    """
    try:
        key = winreg.OpenKey(hive, _STARTUP_APPROVED_SUBKEY, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return None

    with key:
        try:
            data, _value_type = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None

    if not data:
        return None
    return data[0] in _STARTUP_APPROVED_ENABLED_FIRST_BYTES


def _scan_registry_run_keys() -> list[StartupItem]:
    """Return startup items from the registry Run/RunOnce keys (HKCU + HKLM).

    `enabled` reflects StartupApproved's suppression flag where one exists
    for "Run" keys (RunOnce entries aren't managed by Task Manager's
    Startup tab, so there's no corresponding override to check).
    """
    items: list[StartupItem] = []

    for hive, subkey in _REGISTRY_RUN_KEYS:
        try:
            key = winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ)
        except FileNotFoundError:
            continue

        is_run_key = subkey.endswith("\\Run")  # excludes "...\RunOnce"

        with key:
            index = 0
            while True:
                try:
                    name, command, _value_type = winreg.EnumValue(key, index)
                except OSError:
                    break

                enabled = True
                if is_run_key:
                    approved_state = _read_startup_approved_enabled(hive, name)
                    if approved_state is not None:
                        enabled = approved_state

                items.append(
                    StartupItem(
                        name=name,
                        source=StartupSource.REGISTRY_RUN,
                        command=command,
                        enabled=enabled,
                        is_orphaned=_is_orphaned(command),
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


def _apply_known_software(items: list[StartupItem]) -> list[StartupItem]:
    """Fill in known_description/estimated_impact for items that match the
    known-software lookup table; unmatched items are left as None.

    An orphaned item isn't actually running, so any known-software impact
    rating no longer reflects a real resource cost — cleared back to None
    regardless of what the lookup table says. known_description is left
    alone here; the frontend already prioritizes the "appears to be
    uninstalled" message over it for orphaned items.
    """
    for item in items:
        item.known_description, item.estimated_impact = lookup_known_software(item.name, item.command)
        if item.is_orphaned:
            item.estimated_impact = None
    return items


def get_startup_items() -> list[StartupItem]:
    """Return all discovered startup items across the implemented sources.

    TODO: add Scheduled Tasks source.
    """
    user_startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    common_startup = Path(os.environ["PROGRAMDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"

    items = [
        *_scan_startup_folder(user_startup),
        *_scan_startup_folder(common_startup),
        *_scan_registry_run_keys(),
        *_scan_services(),
    ]
    return _apply_known_software(items)

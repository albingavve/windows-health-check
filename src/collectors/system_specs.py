"""Gathers static hardware/OS specs via WMI: CPU, RAM, GPU(s), storage, OS,
and motherboard.

Unlike system_stats.py and process_list.py, this data doesn't change during
a running session — a CPU model or RAM capacity isn't going to change
between two requests a second apart the way live CPU%/memory-usage
readings do. WMI is also meaningfully slower per query here (especially
Win32_VideoController) than the live pollers. So get_system_specs() queries
WMI once per process lifetime and caches the result, instead of the
short-TTL "re-query if stale" cache used for the live endpoints in
server.py — there's no staleness to guard against for hardware that isn't
changing underneath the running process.

Each hardware category is queried independently and degrades to
None/empty on failure rather than aborting the whole response — some WMI
classes (Win32_BaseBoard in particular) can be flaky or permission-
sensitive on certain configs/VMs, and a failure there shouldn't take down
the CPU/RAM/GPU/OS data that did succeed.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass

import pythoncom
import wmi


@dataclass
class CpuSpec:
    name: str | None
    physical_cores: int | None
    logical_processors: int | None


@dataclass
class MemoryStickSpec:
    capacity_gb: float
    speed_mhz: int | None
    memory_type: str | None  # e.g. "DDR4" — None when the type code isn't recognized


@dataclass
class MemorySpec:
    total_capacity_gb: float
    sticks: list[MemoryStickSpec]


@dataclass
class GpuSpec:
    name: str


@dataclass
class DiskSpec:
    model: str
    capacity_gb: float


@dataclass
class OsSpec:
    name: str | None
    version: str | None
    build: str | None


@dataclass
class MotherboardSpec:
    manufacturer: str | None
    model: str | None


@dataclass
class SystemSpecs:
    cpu: CpuSpec | None
    memory: MemorySpec | None
    gpus: list[GpuSpec]
    disks: list[DiskSpec]
    os: OsSpec | None
    motherboard: MotherboardSpec | None

    def to_dict(self) -> dict:
        return asdict(self)


@contextmanager
def _com_initialized():
    """Ensure COM is initialized on the calling thread.

    FastAPI runs sync route handlers in a worker thread pool, and those
    threads don't have COM initialized by default — win32com/wmi calls fail
    with "CoInitialize has not been called" unless we do this per call. See
    startup_audit.py's identical helper — duplicated here rather than
    imported so each collector module stays independent of the others.
    """
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def _query_cpu(connection: "wmi.WMI") -> CpuSpec | None:
    try:
        processors = connection.Win32_Processor()
    except Exception:
        return None
    if not processors:
        return None

    name = (getattr(processors[0], "Name", None) or "").strip() or None

    core_counts = [p.NumberOfCores for p in processors if getattr(p, "NumberOfCores", None) is not None]
    thread_counts = [
        p.NumberOfLogicalProcessors for p in processors if getattr(p, "NumberOfLogicalProcessors", None) is not None
    ]

    return CpuSpec(
        name=name,
        physical_cores=sum(core_counts) if core_counts else None,
        logical_processors=sum(thread_counts) if thread_counts else None,
    )


# SMBIOSMemoryType codes we can confidently name — see the DMTF SMBIOS spec
# (Type 17). Unrecognized/older codes are left as None rather than guessed.
_MEMORY_TYPE_NAMES = {
    20: "DDR",
    21: "DDR2",
    24: "DDR3",
    26: "DDR4",
    34: "DDR5",
}


def _query_memory(connection: "wmi.WMI") -> MemorySpec | None:
    try:
        sticks_raw = connection.Win32_PhysicalMemory()
    except Exception:
        return None
    if not sticks_raw:
        return None

    sticks: list[MemoryStickSpec] = []
    for stick in sticks_raw:
        capacity_raw = getattr(stick, "Capacity", None)
        if capacity_raw is None:
            continue
        capacity_gb = int(capacity_raw) / (1024**3)

        speed_raw = getattr(stick, "Speed", None)
        speed_mhz = int(speed_raw) if speed_raw is not None else None

        type_code = getattr(stick, "SMBIOSMemoryType", None) or getattr(stick, "MemoryType", None)
        memory_type = _MEMORY_TYPE_NAMES.get(int(type_code)) if type_code is not None else None

        sticks.append(MemoryStickSpec(capacity_gb=capacity_gb, speed_mhz=speed_mhz, memory_type=memory_type))

    if not sticks:
        return None

    return MemorySpec(total_capacity_gb=sum(s.capacity_gb for s in sticks), sticks=sticks)


def _query_gpus(connection: "wmi.WMI") -> list[GpuSpec]:
    try:
        controllers = connection.Win32_VideoController()
    except Exception:
        return []
    return [GpuSpec(name=c.Name) for c in controllers if getattr(c, "Name", None)]


def _query_disks(connection: "wmi.WMI") -> list[DiskSpec]:
    try:
        drives = connection.Win32_DiskDrive()
    except Exception:
        return []

    disks: list[DiskSpec] = []
    for drive in drives:
        model = getattr(drive, "Model", None)
        size_raw = getattr(drive, "Size", None)
        if not model or size_raw is None:
            continue
        disks.append(DiskSpec(model=model.strip(), capacity_gb=int(size_raw) / (1024**3)))
    return disks


def _query_os(connection: "wmi.WMI") -> OsSpec | None:
    try:
        systems = connection.Win32_OperatingSystem()
    except Exception:
        return None
    if not systems:
        return None

    system = systems[0]
    return OsSpec(
        name=getattr(system, "Caption", None),
        version=getattr(system, "Version", None),
        build=getattr(system, "BuildNumber", None),
    )


def _query_motherboard(connection: "wmi.WMI") -> MotherboardSpec | None:
    try:
        boards = connection.Win32_BaseBoard()
    except Exception:
        return None
    if not boards:
        return None

    board = boards[0]
    manufacturer = getattr(board, "Manufacturer", None)
    model = getattr(board, "Product", None)
    if not manufacturer and not model:
        return None
    return MotherboardSpec(manufacturer=manufacturer, model=model)


_cached_specs: SystemSpecs | None = None


def get_system_specs() -> SystemSpecs:
    """Return this machine's hardware/OS specs, querying WMI only on the
    first call and returning the cached result on every call after that —
    see the module docstring for why this differs from the live
    collectors' short-TTL caching."""
    global _cached_specs
    if _cached_specs is not None:
        return _cached_specs

    try:
        with _com_initialized():
            connection = wmi.WMI()
            cpu = _query_cpu(connection)
            memory = _query_memory(connection)
            gpus = _query_gpus(connection)
            disks = _query_disks(connection)
            os_info = _query_os(connection)
            motherboard = _query_motherboard(connection)
    except Exception:
        # WMI itself unavailable (COM init failure, permissions, etc.) —
        # degrade to an all-empty result rather than crashing the endpoint.
        cpu, memory, gpus, disks, os_info, motherboard = None, None, [], [], None, None

    _cached_specs = SystemSpecs(cpu=cpu, memory=memory, gpus=gpus, disks=disks, os=os_info, motherboard=motherboard)
    return _cached_specs

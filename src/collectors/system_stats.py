"""Collects current CPU, memory, disk, and network statistics.

Pure data-gathering module: no printing, no API/UI concerns. Returns a
plain dataclass so it's easy to serialize (API) or assert against (tests).
"""

from dataclasses import dataclass, asdict
import psutil


@dataclass
class SystemSnapshot:
    cpu_percent: float
    cpu_per_core: list[float]
    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    net_sent_mb: float
    net_recv_mb: float

    def to_dict(self) -> dict:
        return asdict(self)


def get_system_snapshot(disk_path: str = "C:\\") -> SystemSnapshot:
    """Return a single point-in-time snapshot of core system stats.

    `cpu_percent` uses a short blocking interval for an accurate reading.
    For frequent polling, consider psutil.cpu_percent(interval=None) after
    an initial warm-up call instead.
    """
    cpu_percent = psutil.cpu_percent(interval=0.5)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(disk_path)
    net = psutil.net_io_counters()

    return SystemSnapshot(
        cpu_percent=cpu_percent,
        cpu_per_core=cpu_per_core,
        memory_percent=mem.percent,
        memory_used_gb=round(mem.used / (1024**3), 2),
        memory_total_gb=round(mem.total / (1024**3), 2),
        disk_percent=disk.percent,
        disk_used_gb=round(disk.used / (1024**3), 2),
        disk_total_gb=round(disk.total / (1024**3), 2),
        net_sent_mb=round(net.bytes_sent / (1024**2), 2),
        net_recv_mb=round(net.bytes_recv / (1024**2), 2),
    )

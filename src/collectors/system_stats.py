"""Collects current CPU, memory, disk, and network statistics.

Pure data-gathering module: no printing, no API/UI concerns. Returns a
plain dataclass so it's easy to serialize (API) or assert against (tests).
"""

import time
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
    # Throughput *rate* (not cumulative totals, unlike net_sent_mb/net_recv_mb
    # above) since the previous snapshot — see _compute_disk_io_rate(). 0.0
    # on the very first call of a process's lifetime, before a baseline exists.
    disk_read_mb_s: float
    disk_write_mb_s: float

    def to_dict(self) -> dict:
        return asdict(self)


# Persistent across polls so disk throughput can be computed as a rate
# (bytes since last poll / time since last poll) rather than a meaningless
# cumulative counter — the same "needs a prior reading to be meaningful"
# problem as psutil.Process.cpu_percent(), see process_list.py's module
# docstring.
_prev_disk_io: tuple[int, int, float] | None = None


def _compute_disk_io_rate(disk_io, now: float) -> tuple[float, float]:
    """Return (read_mb_s, write_mb_s) since the previous call, using a
    module-level baseline. Returns (0.0, 0.0) when no prior reading exists
    yet (first call) or disk counters aren't available on this system."""
    global _prev_disk_io

    if disk_io is None:
        return 0.0, 0.0

    if _prev_disk_io is None:
        _prev_disk_io = (disk_io.read_bytes, disk_io.write_bytes, now)
        return 0.0, 0.0

    prev_read_bytes, prev_write_bytes, prev_time = _prev_disk_io
    _prev_disk_io = (disk_io.read_bytes, disk_io.write_bytes, now)

    elapsed = now - prev_time
    if elapsed <= 0:
        return 0.0, 0.0

    read_mb_s = max(0.0, (disk_io.read_bytes - prev_read_bytes) / (1024**2) / elapsed)
    write_mb_s = max(0.0, (disk_io.write_bytes - prev_write_bytes) / (1024**2) / elapsed)
    return round(read_mb_s, 2), round(write_mb_s, 2)


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
    disk_read_mb_s, disk_write_mb_s = _compute_disk_io_rate(psutil.disk_io_counters(), time.monotonic())

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
        disk_read_mb_s=disk_read_mb_s,
        disk_write_mb_s=disk_write_mb_s,
    )

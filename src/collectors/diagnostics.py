"""Rules-based "why is it slow" diagnostic engine.

Takes an already-computed `SystemSnapshot` (system_stats.py) and list of
`ProcessGroup` (process_list.py) and matches them against a small set of
named signatures, each backed by a threshold documented where it's defined.
This module makes no psutil/wmi calls of its own — it's pure analysis over
data the caller already collected, so it's cheap to run on every poll and
easy to unit-test with synthetic input.

Every signature is deliberately conservative: it only fires, and only names
a specific process/group, when the data actually supports doing so. This
mirrors known_software.py's "unmatched items stay unlabeled rather than
guessing" philosophy — a diagnosis that blames the wrong process is worse
than no diagnosis at all.
"""

from dataclasses import dataclass

from src.collectors.process_list import ProcessGroup
from src.collectors.system_stats import SystemSnapshot


@dataclass
class Diagnosis:
    signature: str
    severity: str  # "info" | "warning"
    summary: str
    evidence: dict

    def to_dict(self) -> dict:
        return {
            "signature": self.signature,
            "severity": self.severity,
            "summary": self.summary,
            "evidence": self.evidence,
        }


# --- CPU dominance -----------------------------------------------------

# A lightly-loaded Windows desktop typically idles well under 20% total
# CPU; a sustained overall load at or above this is worth explaining
# rather than dismissing as background noise.
CPU_ELEVATED_THRESHOLD = 50.0

# System-wide CPU at or above this is heavy enough to call a warning
# rather than just an informational note.
CPU_WARNING_THRESHOLD = 85.0

# A group/process must account for at least this share of total system CPU
# capacity to be named as "the" cause — below this, load is spread across
# enough processes that blaming one would be misleading.
CPU_DOMINANCE_SHARE_THRESHOLD = 0.5

# Within a dominant group, one member must account for at least this share
# of the group's own CPU to be named individually (e.g. "Firefox's GPU
# Process") rather than attributing the load to the whole group.
MEMBER_DOMINANCE_SHARE_THRESHOLD = 0.6


def _diagnose_cpu_dominance(stats: SystemSnapshot, groups: list[ProcessGroup]) -> Diagnosis | None:
    if stats.cpu_percent < CPU_ELEVATED_THRESHOLD or not groups:
        return None

    core_count = len(stats.cpu_per_core) or 1
    top_group = max(groups, key=lambda g: g.total_cpu_percent)
    if top_group.total_cpu_percent <= 0:
        return None

    # psutil's per-process cpu_percent is relative to a single core (can
    # exceed 100 on a multi-core system), while stats.cpu_percent is already
    # normalized to 0-100 across the whole machine. Convert the group's total
    # onto that same scale before comparing the two.
    group_share_of_system = (top_group.total_cpu_percent / core_count) / stats.cpu_percent
    if group_share_of_system < CPU_DOMINANCE_SHARE_THRESHOLD:
        return None

    dominant_member = max(top_group.members, key=lambda m: m.cpu_percent, default=None)
    name = top_group.label
    reported_cpu_percent = top_group.total_cpu_percent
    if (
        dominant_member is not None
        and dominant_member.cpu_percent / top_group.total_cpu_percent >= MEMBER_DOMINANCE_SHARE_THRESHOLD
    ):
        reported_cpu_percent = dominant_member.cpu_percent
        if dominant_member.role:
            stem = top_group.label.replace(" (Group)", "")
            name = f"{stem}'s {dominant_member.role}"
        else:
            name = dominant_member.name

    severity = "warning" if stats.cpu_percent >= CPU_WARNING_THRESHOLD else "info"

    return Diagnosis(
        signature="cpu_dominance",
        severity=severity,
        summary=(
            f"System CPU load is elevated at {stats.cpu_percent:.0f}%, driven mainly by "
            f"{name}, which is using {reported_cpu_percent:.0f}% CPU."
        ),
        evidence={
            "system_cpu_percent": stats.cpu_percent,
            "core_count": core_count,
            "group_label": top_group.label,
            "group_cpu_percent": round(top_group.total_cpu_percent, 1),
            "share_of_system_cpu": round(group_share_of_system, 2),
            "named_as": name,
            "named_cpu_percent": round(reported_cpu_percent, 1),
        },
    )


# --- Memory pressure -----------------------------------------------------

# Matches CLAUDE.md's own example of "high" memory usage worth flagging.
MEMORY_PRESSURE_THRESHOLD = 85.0

# Usage at or above this is close enough to exhaustion (swapping/paging
# becomes likely) to warrant a warning instead of an informational note.
MEMORY_CRITICAL_THRESHOLD = 95.0

# How many of the largest memory consumers to name — enough to explain
# where the memory actually went without listing every process.
TOP_MEMORY_GROUPS_COUNT = 3


def _diagnose_memory_pressure(stats: SystemSnapshot, groups: list[ProcessGroup]) -> Diagnosis | None:
    if stats.memory_percent < MEMORY_PRESSURE_THRESHOLD or not groups:
        return None

    top_groups = sorted(groups, key=lambda g: g.total_memory_mb, reverse=True)[:TOP_MEMORY_GROUPS_COUNT]
    combined_mb = sum(g.total_memory_mb for g in top_groups)
    named = ", ".join(f"{g.label} ({g.total_memory_mb / 1024:.1f} GB)" for g in top_groups)
    severity = "warning" if stats.memory_percent >= MEMORY_CRITICAL_THRESHOLD else "info"

    return Diagnosis(
        signature="memory_pressure",
        severity=severity,
        summary=(
            f"Memory usage is at {stats.memory_percent:.0f}% "
            f"({stats.memory_used_gb:.1f} / {stats.memory_total_gb:.1f} GB). The largest "
            f"consumers are {named} — together that's {combined_mb / 1024:.1f} GB."
        ),
        evidence={
            "memory_percent": stats.memory_percent,
            "memory_used_gb": stats.memory_used_gb,
            "memory_total_gb": stats.memory_total_gb,
            "top_groups": [
                {"label": g.label, "total_memory_mb": round(g.total_memory_mb, 1)} for g in top_groups
            ],
            "top_groups_combined_mb": round(combined_mb, 1),
        },
    )


# --- Disk-bound signature -------------------------------------------------

# Combined read+write throughput (MB/s) sustained enough to call "heavy"
# disk activity on a typical consumer SSD/HDD — well above ordinary
# background chatter but comfortably below a drive's max throughput.
DISK_ACTIVITY_THRESHOLD_MBPS = 20.0

# Throughput at or above this is heavy enough to warrant a warning instead
# of an informational note.
DISK_ACTIVITY_WARNING_MBPS = 60.0

# System CPU at or below this while disk throughput is elevated points at
# an I/O-bound cause rather than a compute-bound one (a real, CPU-heavy
# workload wouldn't also leave CPU idle).
DISK_BOUND_CPU_CEILING = 30.0


def _diagnose_disk_bound(stats: SystemSnapshot) -> Diagnosis | None:
    combined_mb_s = stats.disk_read_mb_s + stats.disk_write_mb_s
    if combined_mb_s < DISK_ACTIVITY_THRESHOLD_MBPS or stats.cpu_percent > DISK_BOUND_CPU_CEILING:
        return None

    severity = "warning" if combined_mb_s >= DISK_ACTIVITY_WARNING_MBPS else "info"

    return Diagnosis(
        signature="disk_bound",
        severity=severity,
        summary=(
            f"Disk activity is high ({combined_mb_s:.1f} MB/s) while CPU usage is low "
            f"({stats.cpu_percent:.0f}%) — this pattern usually means background "
            "indexing, an antivirus scan, or a Windows Update download, not a specific "
            "app you're using. Per-process disk activity isn't tracked yet, so this "
            "can't be narrowed down further."
        ),
        evidence={
            "disk_read_mb_s": stats.disk_read_mb_s,
            "disk_write_mb_s": stats.disk_write_mb_s,
            "combined_disk_mb_s": round(combined_mb_s, 1),
            "system_cpu_percent": stats.cpu_percent,
        },
    )


def diagnose_system(stats: SystemSnapshot, groups: list[ProcessGroup]) -> list[Diagnosis]:
    """Match current stats/process data against each known signature.

    Returns an empty list when nothing crosses a threshold — callers should
    treat that as "nothing unusual detected", not as a missing/failed result.
    """
    candidates = [
        _diagnose_cpu_dominance(stats, groups),
        _diagnose_memory_pressure(stats, groups),
        _diagnose_disk_bound(stats),
    ]
    return [d for d in candidates if d is not None]

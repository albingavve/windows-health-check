"""Enumerates all running processes with live CPU% and memory usage, and
groups them by parent-child relationship (falling back to shared
executable name) so the UI can answer "why does one browser tab use so
much memory" by revealing the many processes underneath it.

Pure data-gathering module: no printing, no API/UI concerns. Returns plain
dataclasses so it's easy to serialize (API) or assert against (tests).

`psutil.Process.cpu_percent()` measures CPU time used *since the previous
call* on that exact object — its first call always returns a meaningless
~0.0 reading. Creating a fresh `psutil.Process` on every poll would mean
every process reports ~0% forever. To get meaningful readings from the
second poll onward, this module keeps a persistent, module-level cache of
`psutil.Process` objects across calls to `get_process_list()`, priming each
one's `cpu_percent()` the first time it's seen.
"""

from dataclasses import asdict, dataclass

import psutil


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    name: str
    cpu_percent: float
    memory_mb: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProcessGroup:
    label: str
    process_count: int
    total_cpu_percent: float
    total_memory_mb: float
    # "parent_child": a real process-ancestry tree (e.g. a browser and its
    #   renderer/GPU/utility processes).
    # "shared_name": no meaningful parent link between members — bucketed
    #   together only because they share an executable name (e.g. several
    #   independent svchost.exe hosts). Kept distinct from parent_child so
    #   the UI can be honest about *why* these are grouped.
    # "single": a lone process, not grouped with anything.
    grouping_method: str
    members: list[ProcessInfo]

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "process_count": self.process_count,
            "total_cpu_percent": round(self.total_cpu_percent, 1),
            "total_memory_mb": round(self.total_memory_mb, 2),
            "grouping_method": self.grouping_method,
            "members": [member.to_dict() for member in self.members],
        }


# Persistent across polls so cpu_percent() has a stable baseline to measure
# from — see the module docstring. Pruned in get_process_list() as
# processes exit.
_process_cache: dict[int, psutil.Process] = {}


def _get_primed_process(pid: int) -> psutil.Process:
    """Return a persistent Process object for `pid`, priming cpu_percent() on first use."""
    process = _process_cache.get(pid)
    if process is None:
        process = psutil.Process(pid)
        process.cpu_percent(interval=None)  # baseline reading — discarded
        _process_cache[pid] = process
    return process


def _get_ppid_map() -> dict[int, int] | None:
    """Return a {pid: ppid} map for every running process in one bulk call.

    `Process.ppid()` recomputes this same system-wide snapshot on *every*
    call — calling it once per process (instead of once total) cost ~2s
    across ~285 processes, the same class of bug as the status() issue
    fixed earlier. psutil doesn't expose a public "get everyone's ppid at
    once" API, so this reaches into its private Windows backend for the
    one bulk lookup it already does internally, returning None if that
    internal ever moves/disappears in a future psutil version so the
    caller can fall back to the slower-but-correct per-process method.
    """
    try:
        from psutil._pswindows import ppid_map

        return ppid_map()
    except Exception:
        return None


def get_process_list() -> list[ProcessInfo]:
    """Return a snapshot of all currently running processes.

    Processes that exit between enumeration and inspection (NoSuchProcess)
    or that can't be inspected without elevated privileges (AccessDenied,
    common for protected system processes) are skipped rather than
    aborting the whole listing.
    """
    results: list[ProcessInfo] = []
    seen_pids: set[int] = set()
    ppid_map = _get_ppid_map()

    # psutil.pids() is a cheap, single syscall just for the pid list. All
    # per-process attribute access below happens on our own persistent,
    # cached Process object (see _get_primed_process) inside one oneshot()
    # block per process, so name/cpu_percent/memory_info share a single
    # batched syscall instead of each paying for its own.
    #
    # Process.status() deliberately isn't queried here: profiling showed it
    # costs ~6ms per process on Windows (proc_is_suspended scans the
    # process's thread suspend-counts — not part of oneshot()'s batchable
    # data, so it's a full-price syscall every time). At ~285 processes
    # that alone was ~1.7s of a ~2.7s total call, and it isn't surfaced in
    # the UI yet — cutting it was most of what got this under a second.
    for pid in psutil.pids():
        seen_pids.add(pid)
        try:
            process = _get_primed_process(pid)
            with process.oneshot():
                name = process.name() or ""
                cpu_percent = process.cpu_percent(interval=None)
                memory_mb = round(process.memory_info().rss / (1024**2), 2)
            ppid = ppid_map[pid] if ppid_map is not None else process.ppid()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        results.append(
            ProcessInfo(
                pid=pid,
                ppid=ppid,
                name=name,
                cpu_percent=cpu_percent,
                memory_mb=memory_mb,
            )
        )

    # Drop cached Process objects for pids no longer running, so the cache
    # doesn't grow unbounded as processes come and go.
    for pid in list(_process_cache):
        if pid not in seen_pids:
            del _process_cache[pid]

    return results


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _build_group(members: list[ProcessInfo], grouping_method: str) -> ProcessGroup:
    members = sorted(members, key=lambda p: p.memory_mb, reverse=True)
    total_cpu = sum(m.cpu_percent for m in members)
    total_memory = sum(m.memory_mb for m in members)

    if grouping_method == "parent_child":
        # All members share a name by construction (see group_processes) —
        # a lightly prettified version reads better than a raw exe name.
        stem = members[0].name.rsplit(".", 1)[0]
        label = stem.capitalize() if stem else members[0].name
    elif grouping_method == "shared_name":
        # No confirmed relationship beyond a shared name — say so plainly
        # rather than implying a single coherent app (see module docstring).
        label = f"{members[0].name} (Group)"
    else:
        label = members[0].name

    return ProcessGroup(
        label=label,
        process_count=len(members),
        total_cpu_percent=total_cpu,
        total_memory_mb=total_memory,
        grouping_method=grouping_method,
        members=members,
    )


def group_processes(processes: list[ProcessInfo]) -> list[ProcessGroup]:
    """Cluster processes primarily by parent-child ancestry, falling back to
    shared executable name for processes with no meaningful parent link.

    A parent-child edge only counts toward a cluster when child and parent
    share an executable name — this is what makes a browser's ~10 same-name
    renderer/GPU/utility processes cluster under it, while *not* lumping
    every unrelated service (svchost.exe, spoolsv.exe, ...) together just
    because they all happen to share a generic supervisor parent
    (services.exe). Processes that end up with no such link (singletons)
    are then merged with any other singletons sharing their exact name —
    e.g. several independent svchost.exe hosts — while already-linked
    multi-process trees are left alone even if another, unrelated instance
    of the same app happens to be running (each is reported as its own
    group, which is the more honest picture).
    """
    by_pid = {p.pid: p for p in processes}
    parent_of: dict[int, int] = {p.pid: p.pid for p in processes}  # union-find

    def find(pid: int) -> int:
        root = pid
        while parent_of[root] != root:
            root = parent_of[root]
        while parent_of[pid] != root:
            parent_of[pid], pid = root, parent_of[pid]
        return root

    def union(pid_a: int, pid_b: int) -> None:
        root_a, root_b = find(pid_a), find(pid_b)
        if root_a != root_b:
            parent_of[root_a] = root_b

    for process in processes:
        parent = by_pid.get(process.ppid)
        if parent is not None and parent.pid != process.pid and _normalize_name(parent.name) == _normalize_name(
            process.name
        ):
            union(process.pid, parent.pid)

    components: dict[int, list[ProcessInfo]] = {}
    for process in processes:
        components.setdefault(find(process.pid), []).append(process)

    groups: list[ProcessGroup] = []
    singletons_by_name: dict[str, list[ProcessInfo]] = {}

    for members in components.values():
        if len(members) == 1:
            singletons_by_name.setdefault(_normalize_name(members[0].name), []).append(members[0])
        else:
            groups.append(_build_group(members, "parent_child"))

    for members in singletons_by_name.values():
        method = "shared_name" if len(members) > 1 else "single"
        groups.append(_build_group(members, method))

    groups.sort(key=lambda g: g.total_memory_mb, reverse=True)
    return groups

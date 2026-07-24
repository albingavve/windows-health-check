from src.collectors.diagnostics import MEMORY_PRESSURE_THRESHOLD, diagnose_system
from src.collectors.process_list import ProcessGroup, ProcessInfo
from src.collectors.system_stats import SystemSnapshot


def _stats(**overrides) -> SystemSnapshot:
    base = dict(
        cpu_percent=10.0,
        cpu_per_core=[10.0, 10.0],
        memory_percent=40.0,
        memory_used_gb=6.0,
        memory_total_gb=16.0,
        disk_percent=50.0,
        disk_used_gb=250.0,
        disk_total_gb=500.0,
        net_sent_mb=100.0,
        net_recv_mb=200.0,
        disk_read_mb_s=0.0,
        disk_write_mb_s=0.0,
    )
    base.update(overrides)
    return SystemSnapshot(**base)


def _proc(pid, name, cpu, memory_mb=100.0, role=None):
    return ProcessInfo(pid=pid, ppid=1, name=name, cpu_percent=cpu, memory_mb=memory_mb, role=role)


def _group(label, members, method="parent_child"):
    return ProcessGroup(
        label=label,
        process_count=len(members),
        total_cpu_percent=sum(m.cpu_percent for m in members),
        total_memory_mb=sum(m.memory_mb for m in members),
        grouping_method=method,
        members=members,
    )


def test_no_findings_when_nothing_crosses_a_threshold():
    stats = _stats()
    groups = [_group("idle.exe", [_proc(1, "idle.exe", cpu=1.0)])]

    assert diagnose_system(stats, groups) == []


# --- CPU dominance ---


def test_cpu_dominance_names_specific_member_when_it_dominates_its_group():
    # 2 cores, system at 70% -> dominance requires group total >= 70.
    # Firefox's GPU process (104) makes up the bulk of the group's 120 total.
    members = [
        _proc(10, "firefox.exe", cpu=104.0, role="GPU Process"),
        _proc(11, "firefox.exe", cpu=10.0, role="Tab Content Process"),
        _proc(12, "firefox.exe", cpu=6.0),
    ]
    firefox_group = _group("Firefox", members)
    stats = _stats(cpu_percent=70.0, cpu_per_core=[70.0, 70.0])

    diagnoses = diagnose_system(stats, [firefox_group])

    cpu_diag = next(d for d in diagnoses if d.signature == "cpu_dominance")
    assert "Firefox's GPU Process" in cpu_diag.summary
    assert "104" in cpu_diag.summary
    assert cpu_diag.severity == "info"
    assert cpu_diag.evidence["group_label"] == "Firefox"


def test_cpu_dominance_names_whole_group_when_load_is_spread_across_members():
    # No single member accounts for >=60% of the group's own CPU, so the
    # group is named collectively rather than pinning it on one process.
    members = [
        _proc(10, "chrome.exe", cpu=40.0),
        _proc(11, "chrome.exe", cpu=35.0),
        _proc(12, "chrome.exe", cpu=25.0),
    ]
    chrome_group = _group("Chrome", members)
    stats = _stats(cpu_percent=90.0, cpu_per_core=[90.0, 90.0])

    diagnoses = diagnose_system(stats, [chrome_group])

    cpu_diag = next(d for d in diagnoses if d.signature == "cpu_dominance")
    assert "Chrome" in cpu_diag.summary
    assert "Chrome's" not in cpu_diag.summary
    assert cpu_diag.severity == "warning"


def test_cpu_dominance_does_not_fire_when_load_is_spread_across_many_groups():
    groups = [
        _group("a.exe", [_proc(1, "a.exe", cpu=20.0)]),
        _group("b.exe", [_proc(2, "b.exe", cpu=20.0)]),
        _group("c.exe", [_proc(3, "c.exe", cpu=20.0)]),
        _group("d.exe", [_proc(4, "d.exe", cpu=20.0)]),
    ]
    stats = _stats(cpu_percent=80.0, cpu_per_core=[80.0, 80.0, 80.0, 80.0])

    diagnoses = diagnose_system(stats, groups)

    assert not any(d.signature == "cpu_dominance" for d in diagnoses)


def test_cpu_dominance_does_not_fire_when_system_cpu_is_not_elevated():
    groups = [_group("solo.exe", [_proc(1, "solo.exe", cpu=95.0)])]
    stats = _stats(cpu_percent=20.0, cpu_per_core=[20.0, 20.0])

    diagnoses = diagnose_system(stats, groups)

    assert not any(d.signature == "cpu_dominance" for d in diagnoses)


# --- Memory pressure ---


def test_memory_pressure_names_top_consumers_and_combined_total():
    groups = [
        _group("Firefox", [_proc(1, "firefox.exe", cpu=1.0, memory_mb=4608.0)]),
        _group("Chrome", [_proc(2, "chrome.exe", cpu=1.0, memory_mb=2048.0)]),
        _group("Discord", [_proc(3, "discord.exe", cpu=1.0, memory_mb=819.2)]),
        _group("small.exe", [_proc(4, "small.exe", cpu=1.0, memory_mb=50.0)]),
    ]
    stats = _stats(memory_percent=91.0, memory_used_gb=14.6, memory_total_gb=16.0)

    diagnoses = diagnose_system(stats, groups)

    mem_diag = next(d for d in diagnoses if d.signature == "memory_pressure")
    assert "Firefox" in mem_diag.summary
    assert "Chrome" in mem_diag.summary
    assert "Discord" in mem_diag.summary
    assert "small.exe" not in mem_diag.summary
    assert mem_diag.severity == "info"
    assert len(mem_diag.evidence["top_groups"]) == 3


def test_memory_pressure_escalates_to_warning_near_exhaustion():
    groups = [_group("Firefox", [_proc(1, "firefox.exe", cpu=1.0, memory_mb=8000.0)])]
    stats = _stats(memory_percent=97.0, memory_used_gb=15.5, memory_total_gb=16.0)

    diagnoses = diagnose_system(stats, groups)

    mem_diag = next(d for d in diagnoses if d.signature == "memory_pressure")
    assert mem_diag.severity == "warning"


def test_memory_pressure_does_not_fire_below_threshold():
    groups = [_group("Firefox", [_proc(1, "firefox.exe", cpu=1.0, memory_mb=8000.0)])]
    stats = _stats(memory_percent=MEMORY_PRESSURE_THRESHOLD - 1)

    diagnoses = diagnose_system(stats, groups)

    assert not any(d.signature == "memory_pressure" for d in diagnoses)


# --- Disk-bound signature ---


def test_disk_bound_fires_on_heavy_io_with_low_cpu_and_does_not_name_a_process():
    stats = _stats(cpu_percent=12.0, disk_read_mb_s=15.0, disk_write_mb_s=10.0)

    diagnoses = diagnose_system(stats, [])

    disk_diag = next(d for d in diagnoses if d.signature == "disk_bound")
    assert "indexing" in disk_diag.summary or "antivirus" in disk_diag.summary
    assert disk_diag.severity == "info"
    # Never fabricates a specific culprit — no per-process disk data exists.
    assert ".exe" not in disk_diag.summary


def test_disk_bound_does_not_fire_when_cpu_is_also_high():
    # Heavy disk throughput alongside heavy CPU reads as a real workload,
    # not idle-machine background activity.
    stats = _stats(cpu_percent=80.0, disk_read_mb_s=30.0, disk_write_mb_s=30.0)

    diagnoses = diagnose_system(stats, [])

    assert not any(d.signature == "disk_bound" for d in diagnoses)


def test_disk_bound_does_not_fire_below_activity_threshold():
    stats = _stats(cpu_percent=5.0, disk_read_mb_s=2.0, disk_write_mb_s=1.0)

    diagnoses = diagnose_system(stats, [])

    assert not any(d.signature == "disk_bound" for d in diagnoses)


def test_disk_bound_escalates_to_warning_at_higher_throughput():
    stats = _stats(cpu_percent=5.0, disk_read_mb_s=40.0, disk_write_mb_s=30.0)

    diagnoses = diagnose_system(stats, [])

    disk_diag = next(d for d in diagnoses if d.signature == "disk_bound")
    assert disk_diag.severity == "warning"

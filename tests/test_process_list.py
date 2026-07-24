from unittest.mock import MagicMock, patch

import psutil

from src.collectors import process_list as process_list_module
from src.collectors.process_list import ProcessInfo, get_process_list, group_processes


def _make_fake_process(name, memory_bytes, cpu_percent_values):
    process = MagicMock()
    process.name.return_value = name
    process.memory_info.return_value = MagicMock(rss=memory_bytes)
    process.cpu_percent.side_effect = cpu_percent_values
    return process


def _proc(pid, ppid, name, cpu=0.0, memory_mb=10.0):
    return ProcessInfo(pid=pid, ppid=ppid, name=name, cpu_percent=cpu, memory_mb=memory_mb)


def test_get_process_list_primes_cpu_percent_and_reuses_process_object():
    process_list_module._process_cache.clear()

    # priming call (discarded), first poll's real read, second poll's real read
    persistent_process = _make_fake_process("foo.exe", 50 * 1024 * 1024, [0.0, 0.0, 12.5])

    with patch("src.collectors.process_list.psutil.pids", return_value=[100]), patch(
        "src.collectors.process_list.psutil.Process", return_value=persistent_process
    ) as mock_process_ctor, patch("src.collectors.process_list._get_ppid_map", return_value={100: 4}):
        first_result = get_process_list()
        second_result = get_process_list()

    # Only constructed once — the same persistent object is reused (and its
    # cpu_percent baseline primed) across polls rather than recreated.
    mock_process_ctor.assert_called_once_with(100)

    # Per-process attribute access is consolidated into a single oneshot()
    # batch rather than separate, individually-expensive syscalls.
    assert persistent_process.oneshot.called

    assert first_result[0].pid == 100
    assert first_result[0].ppid == 4
    assert first_result[0].name == "foo.exe"
    assert first_result[0].memory_mb == 50.0
    assert first_result[0].cpu_percent == 0.0

    assert second_result[0].cpu_percent == 12.5


def test_get_process_list_skips_nosuchprocess_and_accessdenied():
    process_list_module._process_cache.clear()

    def fake_process_ctor(pid):
        if pid == 200:
            # First value is consumed by the priming call inside
            # _get_primed_process; the second is this poll's real read.
            return _make_fake_process("good.exe", 10 * 1024 * 1024, [3.0, 3.0])
        if pid == 201:
            # Process exited between enumeration and inspection.
            raise psutil.NoSuchProcess(pid=201)
        if pid == 202:
            # Protected process — attribute access inside oneshot() denied.
            process = MagicMock()
            process.name.side_effect = psutil.AccessDenied(pid=202)
            return process
        raise AssertionError(f"unexpected pid {pid}")

    with patch("src.collectors.process_list.psutil.pids", return_value=[200, 201, 202]), patch(
        "src.collectors.process_list.psutil.Process", side_effect=fake_process_ctor
    ), patch("src.collectors.process_list._get_ppid_map", return_value={200: 1, 201: 1, 202: 1}):
        results = get_process_list()

    assert [r.pid for r in results] == [200]
    assert results[0].name == "good.exe"
    assert results[0].cpu_percent == 3.0


def test_get_process_list_prunes_cache_for_exited_processes():
    process_list_module._process_cache.clear()

    persistent_process = _make_fake_process("temp.exe", 1024 * 1024, [1.0, 1.0])

    with patch("src.collectors.process_list.psutil.pids", return_value=[300]), patch(
        "src.collectors.process_list.psutil.Process", return_value=persistent_process
    ), patch("src.collectors.process_list._get_ppid_map", return_value={300: 1}):
        get_process_list()

    assert 300 in process_list_module._process_cache

    with patch("src.collectors.process_list.psutil.pids", return_value=[]):
        get_process_list()

    assert 300 not in process_list_module._process_cache


def test_get_process_list_falls_back_to_process_ppid_when_bulk_map_unavailable():
    process_list_module._process_cache.clear()

    persistent_process = _make_fake_process("solo.exe", 1024 * 1024, [0.0, 0.0])
    persistent_process.ppid.return_value = 4

    with patch("src.collectors.process_list.psutil.pids", return_value=[400]), patch(
        "src.collectors.process_list.psutil.Process", return_value=persistent_process
    ), patch("src.collectors.process_list._get_ppid_map", return_value=None):
        result = get_process_list()

    assert result[0].ppid == 4
    persistent_process.ppid.assert_called_once()


# --- group_processes ---


def test_group_processes_clusters_clear_parent_child_hierarchy():
    # A browser-like tree: one root chrome.exe with several same-named
    # children (renderer/GPU/utility-style processes).
    processes = [
        _proc(pid=10, ppid=1, name="chrome.exe", cpu=5.0, memory_mb=300),
        _proc(pid=11, ppid=10, name="chrome.exe", cpu=2.0, memory_mb=150),
        _proc(pid=12, ppid=10, name="chrome.exe", cpu=1.5, memory_mb=120),
        _proc(pid=13, ppid=11, name="chrome.exe", cpu=0.5, memory_mb=80),
    ]

    groups = group_processes(processes)

    assert len(groups) == 1
    group = groups[0]
    assert group.grouping_method == "parent_child"
    assert group.label == "Chrome"
    assert group.process_count == 4
    assert group.total_cpu_percent == 9.0
    assert group.total_memory_mb == 650
    assert {m.pid for m in group.members} == {10, 11, 12, 13}


def test_group_processes_falls_back_to_shared_name_with_no_meaningful_parent_link():
    # Several svchost.exe instances all hosted by the same generic
    # supervisor (services.exe) — not children of each other, so they
    # shouldn't cluster via parent-child, only via shared name.
    processes = [
        _proc(pid=1, ppid=0, name="services.exe", cpu=0.1, memory_mb=10),
        _proc(pid=20, ppid=1, name="svchost.exe", cpu=1.0, memory_mb=40),
        _proc(pid=21, ppid=1, name="svchost.exe", cpu=0.5, memory_mb=30),
        _proc(pid=22, ppid=1, name="svchost.exe", cpu=0.2, memory_mb=20),
    ]

    groups = group_processes(processes)

    svchost_group = next(g for g in groups if "svchost" in g.label.lower())
    assert svchost_group.grouping_method == "shared_name"
    assert svchost_group.label == "svchost.exe (Group)"
    assert svchost_group.process_count == 3
    assert svchost_group.total_memory_mb == 90
    assert {m.pid for m in svchost_group.members} == {20, 21, 22}

    # services.exe itself has no siblings sharing its name — lone process.
    services_group = next(g for g in groups if g.label == "services.exe")
    assert services_group.grouping_method == "single"
    assert services_group.process_count == 1


def test_group_processes_reports_lone_process_ungrouped():
    processes = [
        _proc(pid=1, ppid=0, name="services.exe", cpu=0.0, memory_mb=5),
        _proc(pid=50, ppid=1, name="oddtool.exe", cpu=0.3, memory_mb=15),
    ]

    groups = group_processes(processes)

    oddtool_group = next(g for g in groups if g.label == "oddtool.exe")
    assert oddtool_group.grouping_method == "single"
    assert oddtool_group.process_count == 1
    assert oddtool_group.members[0].pid == 50


def test_group_processes_sorts_groups_by_total_memory_descending():
    processes = [
        _proc(pid=1, ppid=0, name="small.exe", memory_mb=5),
        _proc(pid=2, ppid=0, name="big.exe", memory_mb=500),
        _proc(pid=3, ppid=0, name="medium.exe", memory_mb=50),
    ]

    groups = group_processes(processes)

    assert [g.label for g in groups] == ["big.exe", "medium.exe", "small.exe"]

from src.collectors.system_stats import get_system_snapshot


def test_get_system_snapshot_returns_expected_fields():
    snapshot = get_system_snapshot()
    data = snapshot.to_dict()

    expected_keys = {
        "cpu_percent", "cpu_per_core", "memory_percent", "memory_used_gb",
        "memory_total_gb", "disk_percent", "disk_used_gb", "disk_total_gb",
        "net_sent_mb", "net_recv_mb", "disk_read_mb_s", "disk_write_mb_s",
    }
    assert expected_keys.issubset(data.keys())
    assert 0 <= data["cpu_percent"] <= 100
    assert 0 <= data["memory_percent"] <= 100
    # No prior reading exists yet on the first call of a process's lifetime.
    assert data["disk_read_mb_s"] == 0.0
    assert data["disk_write_mb_s"] == 0.0

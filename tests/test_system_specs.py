from unittest.mock import MagicMock, patch

from src.collectors import system_specs as system_specs_module
from src.collectors.system_specs import get_system_specs


def _fake_connection(**overrides):
    """A MagicMock wmi.WMI() connection returning empty lists for every
    class by default; `overrides` supplies return_value lists for specific
    Win32_* methods by name (e.g. Win32_Processor=[...])."""
    connection = MagicMock()
    for method_name in (
        "Win32_Processor",
        "Win32_PhysicalMemory",
        "Win32_VideoController",
        "Win32_DiskDrive",
        "Win32_OperatingSystem",
        "Win32_BaseBoard",
    ):
        getattr(connection, method_name).return_value = overrides.get(method_name, [])
    return connection


def test_get_system_specs_reads_cpu_ram_gpu_disk_os_motherboard():
    system_specs_module._cached_specs = None

    processor = MagicMock(Name="Intel(R) Core(TM) i7-10700K CPU @ 3.80GHz   ", NumberOfCores=8, NumberOfLogicalProcessors=16)
    stick_a = MagicMock(Capacity=str(16 * 1024**3), Speed=3200, SMBIOSMemoryType=26, MemoryType=0)
    stick_b = MagicMock(Capacity=str(16 * 1024**3), Speed=3200, SMBIOSMemoryType=26, MemoryType=0)
    gpu_integrated = MagicMock(Name="Intel(R) UHD Graphics 630")
    gpu_dedicated = MagicMock(Name="NVIDIA GeForce RTX 3080")
    disk = MagicMock(Model="Samsung SSD 970 EVO Plus 1TB  ", Size=str(1_000_204_886_016))
    os_info = MagicMock(Caption="Microsoft Windows 11 Pro", Version="10.0.26200", BuildNumber="26200")
    board = MagicMock(Manufacturer="ASUSTeK COMPUTER INC.", Product="ROG STRIX Z490-E GAMING")

    connection = _fake_connection(
        Win32_Processor=[processor],
        Win32_PhysicalMemory=[stick_a, stick_b],
        Win32_VideoController=[gpu_integrated, gpu_dedicated],
        Win32_DiskDrive=[disk],
        Win32_OperatingSystem=[os_info],
        Win32_BaseBoard=[board],
    )

    with patch("src.collectors.system_specs.wmi.WMI", return_value=connection):
        specs = get_system_specs()

    assert specs.cpu.name == "Intel(R) Core(TM) i7-10700K CPU @ 3.80GHz"
    assert specs.cpu.physical_cores == 8
    assert specs.cpu.logical_processors == 16

    assert specs.memory.total_capacity_gb == 32.0
    assert len(specs.memory.sticks) == 2
    assert specs.memory.sticks[0].memory_type == "DDR4"
    assert specs.memory.sticks[0].speed_mhz == 3200

    assert {g.name for g in specs.gpus} == {"Intel(R) UHD Graphics 630", "NVIDIA GeForce RTX 3080"}

    assert len(specs.disks) == 1
    assert specs.disks[0].model == "Samsung SSD 970 EVO Plus 1TB"

    assert specs.os.name == "Microsoft Windows 11 Pro"
    assert specs.os.version == "10.0.26200"
    assert specs.os.build == "26200"

    assert specs.motherboard.manufacturer == "ASUSTeK COMPUTER INC."
    assert specs.motherboard.model == "ROG STRIX Z490-E GAMING"


def test_get_system_specs_degrades_field_by_field_on_partial_wmi_failure():
    system_specs_module._cached_specs = None

    connection = _fake_connection(
        Win32_Processor=[MagicMock(Name="Some CPU", NumberOfCores=4, NumberOfLogicalProcessors=8)],
    )
    # GPU query is flaky/permission-sensitive on some configs — simulate a
    # failure there specifically and confirm everything else still comes
    # back rather than the whole response failing.
    connection.Win32_VideoController.side_effect = Exception("WMI query failed")
    connection.Win32_BaseBoard.side_effect = Exception("WMI query failed")

    with patch("src.collectors.system_specs.wmi.WMI", return_value=connection):
        specs = get_system_specs()

    assert specs.cpu is not None
    assert specs.cpu.name == "Some CPU"
    assert specs.gpus == []
    assert specs.motherboard is None


def test_get_system_specs_degrades_entirely_when_wmi_connection_fails():
    system_specs_module._cached_specs = None

    with patch("src.collectors.system_specs.wmi.WMI", side_effect=Exception("COM error")):
        specs = get_system_specs()

    assert specs.cpu is None
    assert specs.memory is None
    assert specs.gpus == []
    assert specs.disks == []
    assert specs.os is None
    assert specs.motherboard is None


def test_get_system_specs_queries_wmi_only_once_across_multiple_calls():
    system_specs_module._cached_specs = None

    connection = _fake_connection(
        Win32_Processor=[MagicMock(Name="Some CPU", NumberOfCores=4, NumberOfLogicalProcessors=8)],
    )

    with patch("src.collectors.system_specs.wmi.WMI", return_value=connection) as mock_wmi_ctor:
        first = get_system_specs()
        second = get_system_specs()
        third = get_system_specs()

    mock_wmi_ctor.assert_called_once()
    assert first is second is third

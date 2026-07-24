import winreg
from unittest.mock import MagicMock, patch

from src.collectors.startup_audit import (
    StartupSource,
    _scan_registry_run_keys,
    _scan_services,
    _scan_startup_folder,
    get_startup_items,
)


def test_scan_startup_folder_plain_file(tmp_path):
    (tmp_path / "SomeApp.exe").write_text("")
    (tmp_path / "desktop.ini").write_text("")  # should be skipped

    items = _scan_startup_folder(tmp_path)

    assert len(items) == 1
    item = items[0]
    assert item.name == "SomeApp"
    assert item.source == StartupSource.STARTUP_FOLDER
    assert item.command == str(tmp_path / "SomeApp.exe")
    assert item.enabled is True


def test_scan_startup_folder_missing_directory(tmp_path):
    assert _scan_startup_folder(tmp_path / "does-not-exist") == []


def test_scan_startup_folder_resolves_shortcut(tmp_path):
    (tmp_path / "OneDrive.lnk").write_text("")

    fake_shortcut = MagicMock(Targetpath=r"C:\Program Files\OneDrive\OneDrive.exe", Arguments="/background")
    fake_shell = MagicMock()
    fake_shell.CreateShortCut.return_value = fake_shortcut

    with patch("src.collectors.startup_audit.win32com.client.Dispatch", return_value=fake_shell):
        items = _scan_startup_folder(tmp_path)

    assert len(items) == 1
    assert items[0].command == r"C:\Program Files\OneDrive\OneDrive.exe /background"


def test_scan_startup_folder_shortcut_resolution_falls_back_on_error(tmp_path):
    lnk_path = tmp_path / "Broken.lnk"
    lnk_path.write_text("")

    with patch("src.collectors.startup_audit.win32com.client.Dispatch", side_effect=Exception("COM error")):
        items = _scan_startup_folder(tmp_path)

    assert len(items) == 1
    assert items[0].command == str(lnk_path)


def test_scan_registry_run_keys_reads_values_and_skips_missing_keys():
    hkcu_run_key = MagicMock()
    hklm_run_key = MagicMock()

    registry_values = {
        id(hkcu_run_key): [("Steam", r"C:\Steam\steam.exe -silent", winreg.REG_SZ)],
        id(hklm_run_key): [],
    }

    def fake_open_key(hive, subkey, *_args, **_kwargs):
        if (hive, subkey) == (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"):
            return hkcu_run_key
        if (hive, subkey) == (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"):
            return hklm_run_key
        raise FileNotFoundError

    def fake_enum_value(key, index):
        values = registry_values[id(key)]
        if index >= len(values):
            raise OSError
        return values[index]

    with patch("src.collectors.startup_audit.winreg.OpenKey", side_effect=fake_open_key), patch(
        "src.collectors.startup_audit.winreg.EnumValue", side_effect=fake_enum_value
    ):
        items = _scan_registry_run_keys()

    assert len(items) == 1
    item = items[0]
    assert item.name == "Steam"
    assert item.command == r"C:\Steam\steam.exe -silent"
    assert item.source == StartupSource.REGISTRY_RUN
    assert item.enabled is True


def test_get_startup_items_combines_all_sources(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    programdata = tmp_path / "programdata"
    user_startup = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    common_startup = programdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    user_startup.mkdir(parents=True)
    common_startup.mkdir(parents=True)
    (user_startup / "UserApp.exe").write_text("")
    (common_startup / "CommonApp.exe").write_text("")

    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("PROGRAMDATA", str(programdata))

    with patch("src.collectors.startup_audit._scan_registry_run_keys", return_value=[]), patch(
        "src.collectors.startup_audit._scan_services", return_value=[]
    ):
        items = get_startup_items()

    names = {item.name for item in items}
    assert names == {"UserApp", "CommonApp"}
    assert all(item.source == StartupSource.STARTUP_FOLDER for item in items)


def test_scan_services_maps_fields_and_start_mode_to_enabled():
    auto_service = MagicMock(
        DisplayName="Windows Update",
        Name="wuauserv",
        PathName=r"C:\WINDOWS\system32\svchost.exe -k netsvcs",
        StartMode="Auto",
    )
    manual_service = MagicMock(
        DisplayName="",
        Name="SomeManualSvc",
        PathName=r"C:\WINDOWS\system32\some.exe",
        StartMode="Manual",
    )

    fake_connection = MagicMock()
    fake_connection.Win32_Service.return_value = [auto_service, manual_service]

    with patch("src.collectors.startup_audit.wmi.WMI", return_value=fake_connection):
        items = _scan_services()

    assert len(items) == 2
    assert all(item.source == StartupSource.SERVICE for item in items)

    update_item = next(i for i in items if i.name == "Windows Update")
    assert update_item.command == r"C:\WINDOWS\system32\svchost.exe -k netsvcs"
    assert update_item.enabled is True

    manual_item = next(i for i in items if i.name == "SomeManualSvc")
    assert manual_item.enabled is False


def test_scan_services_returns_empty_list_on_wmi_failure():
    with patch("src.collectors.startup_audit.wmi.WMI", side_effect=Exception("WMI unavailable")):
        assert _scan_services() == []


def test_get_startup_items_enriches_known_and_unknown_items(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    programdata = tmp_path / "programdata"
    user_startup = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    common_startup = programdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    user_startup.mkdir(parents=True)
    common_startup.mkdir(parents=True)
    (user_startup / "Discord.exe").write_text("")
    (common_startup / "SomeRandomTool.exe").write_text("")

    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("PROGRAMDATA", str(programdata))

    with patch("src.collectors.startup_audit._scan_registry_run_keys", return_value=[]), patch(
        "src.collectors.startup_audit._scan_services", return_value=[]
    ):
        items = get_startup_items()

    discord_item = next(i for i in items if i.name == "Discord")
    assert discord_item.known_description is not None
    assert discord_item.estimated_impact == "medium"

    unknown_item = next(i for i in items if i.name == "SomeRandomTool")
    assert unknown_item.known_description is None
    assert unknown_item.estimated_impact is None

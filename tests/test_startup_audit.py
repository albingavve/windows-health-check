import winreg
from unittest.mock import MagicMock, patch

from src.collectors.startup_audit import (
    StartupItem,
    StartupSource,
    _apply_known_software,
    _extract_executable_path,
    _is_orphaned,
    _read_startup_approved_enabled,
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


def test_extract_executable_path_handles_quoted_and_unquoted_commands():
    assert _extract_executable_path('"C:\\Program Files\\App\\app.exe" --flag') == r"C:\Program Files\App\app.exe"
    assert (
        _extract_executable_path(r"C:\Windows\System32\rundll32.exe shell32.dll,Thing")
        == r"C:\Windows\System32\rundll32.exe"
    )
    assert _extract_executable_path(r"C:\Tools\solo.exe") == r"C:\Tools\solo.exe"
    assert _extract_executable_path("   ") is None
    assert _extract_executable_path("") is None


def test_is_orphaned_flags_missing_absolute_path(tmp_path):
    missing = tmp_path / "GoneApp" / "app.exe"
    assert _is_orphaned(f'"{missing}" --background') is True


def test_is_orphaned_does_not_flag_existing_absolute_path(tmp_path):
    existing = tmp_path / "app.exe"
    existing.write_text("")
    assert _is_orphaned(f'"{existing}" --background') is False


def test_is_orphaned_does_not_flag_bare_relative_command():
    # A bare filename could still resolve via the system PATH — that can't
    # be verified here, so it must not be guessed at as orphaned.
    assert _is_orphaned("rundll32.exe shell32.dll,Thing") is False


def test_read_startup_approved_enabled_true_for_enabled_first_byte():
    key = MagicMock()
    with patch("src.collectors.startup_audit.winreg.OpenKey", return_value=key), patch(
        "src.collectors.startup_audit.winreg.QueryValueEx", return_value=(bytes([0x02, 0, 0, 0]), winreg.REG_BINARY)
    ):
        assert _read_startup_approved_enabled(winreg.HKEY_CURRENT_USER, "Steam") is True


def test_read_startup_approved_enabled_false_for_disabled_first_byte():
    key = MagicMock()
    disabled_value = bytes([0x03, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8])  # 0x03 + FILETIME of when disabled
    with patch("src.collectors.startup_audit.winreg.OpenKey", return_value=key), patch(
        "src.collectors.startup_audit.winreg.QueryValueEx", return_value=(disabled_value, winreg.REG_BINARY)
    ):
        assert _read_startup_approved_enabled(winreg.HKEY_CURRENT_USER, "Teams") is False


def test_read_startup_approved_enabled_none_when_key_or_value_missing():
    with patch("src.collectors.startup_audit.winreg.OpenKey", side_effect=FileNotFoundError):
        assert _read_startup_approved_enabled(winreg.HKEY_CURRENT_USER, "Anything") is None

    key = MagicMock()
    with patch("src.collectors.startup_audit.winreg.OpenKey", return_value=key), patch(
        "src.collectors.startup_audit.winreg.QueryValueEx", side_effect=FileNotFoundError
    ):
        assert _read_startup_approved_enabled(winreg.HKEY_CURRENT_USER, "NotOverridden") is None


def test_scan_registry_run_keys_applies_startup_approved_state_and_orphan_detection(tmp_path):
    hkcu_run_key = MagicMock()
    hkcu_approved_key = MagicMock()

    existing_exe = tmp_path / "GoodApp.exe"
    existing_exe.write_text("")
    missing_exe = tmp_path / "GoneApp.exe"

    registry_values = {
        id(hkcu_run_key): [
            ("GoodApp", f'"{existing_exe}"', winreg.REG_SZ),
            ("DisabledApp", f'"{existing_exe}"', winreg.REG_SZ),
            ("GoneApp", f'"{missing_exe}"', winreg.REG_SZ),
        ],
    }
    approved_values = {
        "GoodApp": (bytes([0x02, 0, 0, 0]), winreg.REG_BINARY),
        "DisabledApp": (bytes([0x03] + [0] * 11), winreg.REG_BINARY),
        # "GoneApp" intentionally has no override — defaults to enabled.
    }

    def fake_open_key(hive, subkey, *_args, **_kwargs):
        if (hive, subkey) == (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"):
            return hkcu_run_key
        if (hive, subkey) == (
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run",
        ):
            return hkcu_approved_key
        raise FileNotFoundError

    def fake_enum_value(key, index):
        values = registry_values.get(id(key), [])
        if index >= len(values):
            raise OSError
        return values[index]

    def fake_query_value_ex(key, name):
        if name not in approved_values:
            raise FileNotFoundError
        return approved_values[name]

    with patch("src.collectors.startup_audit.winreg.OpenKey", side_effect=fake_open_key), patch(
        "src.collectors.startup_audit.winreg.EnumValue", side_effect=fake_enum_value
    ), patch("src.collectors.startup_audit.winreg.QueryValueEx", side_effect=fake_query_value_ex):
        items = _scan_registry_run_keys()

    by_name = {item.name: item for item in items}
    assert len(items) == 3

    # Enabled per StartupApproved, and its executable still exists.
    assert by_name["GoodApp"].enabled is True
    assert by_name["GoodApp"].is_orphaned is False

    # Run key entry is present, but StartupApproved's suppression flag
    # means Task Manager's "Disable" was actually used — the true state.
    assert by_name["DisabledApp"].enabled is False
    assert by_name["DisabledApp"].is_orphaned is False

    # No StartupApproved override recorded -> defaults to enabled, but the
    # executable is gone -> flagged as an orphaned leftover entry.
    assert by_name["GoneApp"].enabled is True
    assert by_name["GoneApp"].is_orphaned is True


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


def test_apply_known_software_clears_impact_for_orphaned_items_but_keeps_description():
    # Matches "discord" in the known-software table, which would normally
    # get a "medium" impact rating — but it's orphaned (exe is gone), so it
    # isn't actually running and has no real resource cost to report.
    orphaned_item = StartupItem(
        name="Discord",
        source=StartupSource.REGISTRY_RUN,
        command=r"C:\Users\someone\AppData\Local\Discord\Update.exe --processStart Discord.exe",
        enabled=True,
        is_orphaned=True,
    )
    normal_item = StartupItem(
        name="Discord",
        source=StartupSource.REGISTRY_RUN,
        command=r"C:\Users\someone\AppData\Local\Discord\Update.exe --processStart Discord.exe",
        enabled=True,
        is_orphaned=False,
    )

    _apply_known_software([orphaned_item, normal_item])

    assert orphaned_item.estimated_impact is None
    assert orphaned_item.known_description is not None  # lookup result still present

    assert normal_item.estimated_impact == "medium"
    assert normal_item.known_description is not None

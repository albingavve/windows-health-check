import winreg
from unittest.mock import MagicMock, patch

from src.collectors.startup_audit import (
    StartupSource,
    _scan_registry_run_keys,
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

    with patch("src.collectors.startup_audit._scan_registry_run_keys", return_value=[]):
        items = get_startup_items()

    names = {item.name for item in items}
    assert names == {"UserApp", "CommonApp"}
    assert all(item.source == StartupSource.STARTUP_FOLDER for item in items)

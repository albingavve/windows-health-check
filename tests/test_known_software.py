from src.collectors.known_software import lookup_known_software


def test_lookup_matched_item_returns_description_and_impact():
    description, impact = lookup_known_software("Discord", r"C:\Users\Test\AppData\Local\Discord\Update.exe --processStart Discord.exe")

    assert description is not None
    assert "Discord" in description
    assert impact == "medium"


def test_lookup_unmatched_item_returns_none_none():
    description, impact = lookup_known_software("SomeRandomTool", r"C:\Program Files\SomeRandomTool\tool.exe")

    assert description is None
    assert impact is None


def test_lookup_is_case_insensitive_on_name_and_command():
    description, impact = lookup_known_software("ONEDRIVE", r"C:\PROGRAM FILES\MICROSOFT ONEDRIVE\ONEDRIVE.EXE /BACKGROUND")

    assert description is not None
    assert impact == "low"

    # Match can also come purely from the command when the name doesn't hint at it.
    description_from_command, impact_from_command = lookup_known_software("Background Sync Helper", r"C:\Program Files\NordVPN\NordVPN.exe")

    assert description_from_command is not None
    assert impact_from_command == "low"

from unittest.mock import MagicMock, patch

from src.collectors.device_inventory import (
    _DISPLAYCONFIG_PATH_INFO,
    _RawPnpEntity,
    UsbDevice,
    _decode_edid_string,
    _extract_hardware_id,
    _extract_vid,
    _get_builtin_display_hardware_ids,
    _group_usb_devices,
    _hardware_id_from_monitor_device_path,
    _index_usb_devices_by_hardware_key,
    _is_generic_plumbing,
    _pnp_grouping_key,
    _query_keyboards,
    get_device_inventory,
)

_DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL = 0x80000000


def _fake_pnp_entity(status="OK", name="Some Device", manufacturer="Some Corp", device_id=r"USB\VID_0000&PID_0000\1"):
    return MagicMock(Status=status, Name=name, Manufacturer=manufacturer, DeviceID=device_id)


def _query_router(usb_entities=None, keyboard_entities=None):
    """A connection.query() side_effect that returns different canned
    results depending on which WQL query was issued — USB devices and
    keyboards are now two separate queries against Win32_PnPEntity, and a
    single shared return_value would incorrectly leak USB rows into
    keyboard results (and vice versa) in tests exercising both."""

    def fake_query(wql):
        if "PNPClass='Keyboard'" in wql:
            return keyboard_entities or []
        if "USB%" in wql:
            return usb_entities or []
        return []

    return fake_query


def _fake_monitor_id(manufacturer_chars, model_chars, instance_name):
    return MagicMock(
        ManufacturerName=manufacturer_chars,
        UserFriendlyName=model_chars,
        InstanceName=instance_name,
    )


def _ascii_to_uint16_array(text, padded_length=None):
    """Build a NUL-padded UInt16 array the way WmiMonitorID actually
    returns these fields, for use as test input."""
    values = [ord(c) for c in text]
    if padded_length:
        values += [0] * (padded_length - len(values))
    return values


def _make_path_info(output_technology, target_id):
    path = _DISPLAYCONFIG_PATH_INFO()
    path.targetInfo.outputTechnology = output_technology
    path.targetInfo.id = target_id
    path.targetInfo.adapterId.LowPart = 1
    path.targetInfo.adapterId.HighPart = 0
    return path


# --- EDID byte-array decoding (the trickiest part) ---


def test_decode_edid_string_decodes_nul_padded_uint16_array():
    values = _ascii_to_uint16_array("ACI", padded_length=8)
    assert values == [65, 67, 73, 0, 0, 0, 0, 0]
    assert _decode_edid_string(values) == "ACI"


def test_decode_edid_string_decodes_a_realistic_friendly_name():
    values = _ascii_to_uint16_array("ROG PG279Q", padded_length=14)
    assert _decode_edid_string(values) == "ROG PG279Q"


def test_decode_edid_string_returns_none_for_empty_or_all_nul_or_none():
    assert _decode_edid_string([]) is None
    assert _decode_edid_string([0, 0, 0, 0]) is None
    assert _decode_edid_string(None) is None


def test_extract_hardware_id_takes_the_middle_pnp_id_segment():
    assert _extract_hardware_id(r"DISPLAY\ACI27EA\4&39c00d2&0&UID4352_0") == "ACI27EA"
    assert _extract_hardware_id(r"MONITOR\ACI27EA\{4d36e96e-e325}\0000") == "ACI27EA"


def test_extract_hardware_id_handles_missing_or_malformed_input():
    assert _extract_hardware_id(None) is None
    assert _extract_hardware_id("") is None
    assert _extract_hardware_id("NoBackslashesAtAll") is None


# --- USB enumeration ---


def test_get_device_inventory_uses_filtered_wql_queries_not_the_bare_class_call():
    # Win32_PnPEntity() with no WHERE clause fetches every property of
    # every PnP device system-wide (often 1000+ entries) and was measured
    # taking 30+ seconds — this locks in the fix (targeted WQL queries)
    # so a future edit can't silently regress back to the slow call.
    connection = MagicMock()
    connection.query.return_value = []
    connection.WmiMonitorID.return_value = []

    with patch("src.collectors.device_inventory.wmi.WMI", return_value=connection):
        get_device_inventory()

    assert connection.query.call_count == 2
    query_strings = [call.args[0] for call in connection.query.call_args_list]
    assert any("Win32_PnPEntity" in q and "USB" in q for q in query_strings)
    assert any("PNPClass='Keyboard'" in q for q in query_strings)
    connection.Win32_PnPEntity.assert_not_called()


def test_get_device_inventory_filters_usb_devices_to_present_ok_status_only():
    entities = [
        _fake_pnp_entity(
            status="OK", name="Corsair Mouse", manufacturer="Corsair", device_id=r"USB\VID_1B1C&PID_1B3C\1"
        ),
        _fake_pnp_entity(status="Error", name="Ghosted USB Device", manufacturer=None),
    ]
    connection = MagicMock()
    connection.query.side_effect = _query_router(usb_entities=entities)
    connection.WmiMonitorID.return_value = []

    with patch("src.collectors.device_inventory.wmi.WMI", return_value=connection):
        inventory = get_device_inventory()

    assert len(inventory.usb_devices) == 1
    assert inventory.usb_devices[0].name == "Corsair Mouse"
    assert inventory.usb_devices[0].manufacturer == "Corsair"
    assert inventory.usb_devices[0].is_generic is False


def test_get_device_inventory_degrades_to_empty_usb_list_on_query_failure():
    connection = MagicMock()
    connection.query.side_effect = Exception("WMI query failed")
    connection.WmiMonitorID = MagicMock(return_value=[])

    with patch("src.collectors.device_inventory.wmi.WMI", return_value=connection):
        inventory = get_device_inventory()

    assert inventory.usb_devices == []
    assert inventory.keyboards == []


# --- PNP grouping (same-parent dedup) — shared by USB and keyboards ---


def test_pnp_grouping_key_collapses_sibling_interfaces_of_one_composite_device():
    key_a = _pnp_grouping_key(r"USB\VID_046D&PID_405E&MI_00\6&2d5f6a3c&0&0000")
    key_b = _pnp_grouping_key(r"USB\VID_046D&PID_405E&MI_02\6&2d5f6a3c&0&0002")
    assert key_a == key_b == "VID_046D&PID_405E"


def test_pnp_grouping_key_leaves_single_interface_devices_alone():
    assert _pnp_grouping_key(r"USB\VID_1B1C&PID_1B3C\6&abc123&0&1") == "VID_1B1C&PID_1B3C"


def test_pnp_grouping_key_handles_malformed_device_id():
    assert _pnp_grouping_key("NoBackslashesAtAll") == "NoBackslashesAtAll"


def test_pnp_grouping_key_works_for_acpi_ids_too():
    assert _pnp_grouping_key(r"ACPI\MSFT0003\0") == "MSFT0003"


def test_pnp_grouping_key_collapses_non_mi_composite_suffixes_too():
    # Real bug found on this project's own dev machine: a Logitech
    # LIGHTSPEED receiver's extra "Lamp Array" RGB interfaces enumerate
    # with a "&LAMPARRAY" suffix, not "&MI_XX" — the old MI_-only stripping
    # logic left this suffix untouched, so these rows grouped under a
    # different key than the receiver's own row and it showed up twice in
    # the Devices popup.
    key_a = _pnp_grouping_key(r"USB\VID_046D&PID_C54D\3957336F3135")
    key_b = _pnp_grouping_key(r"USB\VID_046D&PID_C54D&LAMPARRAY\6&20CA14AB&0&3957336F3135_SLOT00")
    assert key_a == key_b == "VID_046D&PID_C54D"


def test_extract_vid_pulls_the_vendor_id_out_of_a_hardware_key():
    assert _extract_vid("VID_046D&PID_C54D") == "046D"
    assert _extract_vid("MSFT0003") is None


def test_group_usb_devices_collapses_seven_sibling_interfaces_into_one_entry():
    # Matches the real-world case this feature was built for: a Logitech
    # LIGHTSPEED receiver enumerating as 7 Win32_PnPEntity rows, all named
    # identically, none reporting a manufacturer.
    raw = [
        _RawPnpEntity(
            name="LIGHTSPEED Receiver",
            manufacturer=None,
            device_id=rf"USB\VID_046D&PID_C52B&MI_0{i}\6&2d5f6a3c&0&000{i}",
        )
        for i in range(7)
    ]

    devices = _group_usb_devices(raw)

    assert len(devices) == 1
    device = devices[0]
    assert device.interface_count == 7
    assert device.name == "LIGHTSPEED Receiver"
    # known_devices.py fills in the manufacturer Windows left blank.
    assert device.manufacturer == "Logitech"
    assert device.category == "Wireless Mouse/Keyboard Receiver"
    assert device.is_generic is False


def test_group_usb_devices_collapses_lightspeed_receiver_lamparray_interfaces():
    # Real-shaped DeviceIDs captured from this project's own dev machine
    # while investigating a duplicate "LIGHTSPEED Receiver" entry: the
    # receiver's base row has no MI_/LAMPARRAY suffix at all, while its
    # seven RGB "Lamp Array" interfaces all share a "&LAMPARRAY" suffix
    # instead of the usual "&MI_XX" one. Before the _pnp_grouping_key fix,
    # these grouped separately and produced two "LIGHTSPEED Receiver" rows
    # for one physical device.
    raw = [
        _RawPnpEntity(
            name="LIGHTSPEED Receiver",
            manufacturer="Logitech",
            device_id=r"USB\VID_046D&PID_C54D\3957336F3135",
        ),
        *[
            _RawPnpEntity(
                name="LIGHTSPEED Receiver",
                manufacturer=None,
                device_id=rf"USB\VID_046D&PID_C54D&LAMPARRAY\6&20CA14AB&0&3957336F3135_SLOT0{i}",
            )
            for i in range(7)
        ],
    ]

    devices = _group_usb_devices(raw)

    assert len(devices) == 1
    device = devices[0]
    assert device.interface_count == 8
    assert device.name == "LIGHTSPEED Receiver"
    assert device.manufacturer == "Logitech"
    assert device.category == "Wireless Mouse/Keyboard Receiver"


def test_group_usb_devices_does_not_merge_unrelated_devices_sharing_a_generic_name():
    # Two distinct physical devices that both happen to report the generic
    # Windows name "USB Input Device" must NOT be merged just because the
    # name matches — only a shared hardware-ID prefix should merge them.
    raw = [
        _RawPnpEntity(name="USB Input Device", manufacturer="(Standard system devices)", device_id=r"USB\VID_AAAA&PID_1111\1"),
        _RawPnpEntity(name="USB Input Device", manufacturer="(Standard system devices)", device_id=r"USB\VID_BBBB&PID_2222\1"),
    ]

    devices = _group_usb_devices(raw)

    assert len(devices) == 2
    assert all(d.interface_count == 1 for d in devices)
    assert all(d.is_generic for d in devices)


def test_group_usb_devices_prefers_a_specifically_named_sibling_over_a_generic_wrapper_row():
    # Real-world case this regression-tests: a composite USB audio device
    # enumerates a generic "USB Composite Device" wrapper row *and* a
    # specifically-named interface row under the same hardware ID — and
    # WMI returned the generic one FIRST. Naively taking members[0] would
    # silently swallow "ROG PELTA (2.4GHz)" under the generic name, hiding
    # a real, recognizable device inside the generic-plumbing bucket.
    raw = [
        _RawPnpEntity(
            name="USB Composite Device",
            manufacturer="(Standard USB Host Controller)",
            device_id=r"USB\VID_0B05&PID_1B84\6&3230633&0&0000",
        ),
        _RawPnpEntity(
            name="ROG PELTA (2.4GHz)",
            manufacturer="(Generic USB Audio)",
            device_id=r"USB\VID_0B05&PID_1B84&MI_00\6&3230633&0&0000",
        ),
    ]

    devices = _group_usb_devices(raw)

    assert len(devices) == 1
    device = devices[0]
    assert device.name == "ROG PELTA (2.4GHz)"
    assert device.category == "Headset/Audio"
    assert device.is_generic is False
    assert device.interface_count == 2


def test_group_usb_devices_prefers_a_non_null_manufacturer_from_any_sibling():
    raw = [
        _RawPnpEntity(name="Some Composite Peripheral", manufacturer=None, device_id=r"USB\VID_2222&PID_3333&MI_00\1"),
        _RawPnpEntity(name="Some Composite Peripheral", manufacturer="RealVendor Inc.", device_id=r"USB\VID_2222&PID_3333&MI_01\1"),
    ]

    devices = _group_usb_devices(raw)

    assert len(devices) == 1
    assert devices[0].manufacturer == "RealVendor Inc."
    assert devices[0].interface_count == 2


# --- generic-plumbing classification ---


def test_is_generic_plumbing_flags_hubs_and_composite_wrappers():
    assert _is_generic_plumbing("USB Root Hub (USB 3.0)", "(Standard USB HUBs)") is True
    assert _is_generic_plumbing("Generic SuperSpeed USB Hub", "(Standard USB HUBs)") is True
    assert _is_generic_plumbing("USB Composite Device", "(Standard USB Host Controller)") is True
    assert _is_generic_plumbing("USB4 Root Router (1.0)", "Generic USB4 Device Router") is True
    assert _is_generic_plumbing("USB Input Device", "(Standard system devices)") is True


def test_is_generic_plumbing_does_not_flag_real_peripherals():
    assert _is_generic_plumbing("Corsair K70 Keyboard", "Corsair") is False
    assert _is_generic_plumbing("LIGHTSPEED Receiver", "Logitech") is False
    # Missing manufacturer alone (with an otherwise unremarkable name)
    # isn't enough on its own to hide a possibly-real device.
    assert _is_generic_plumbing("Some Unrecognized Gadget", None) is False


# --- keyboards: ACPI (built-in) vs USB/HID (external) ---


def test_query_keyboards_uses_pnpclass_keyboard_filter():
    connection = MagicMock()
    connection.query.return_value = []

    result = _query_keyboards(connection, {})

    assert result == []
    connection.query.assert_called_once()
    query_string = connection.query.call_args[0][0]
    assert "Win32_PnPEntity" in query_string
    assert "PNPClass='Keyboard'" in query_string


def test_query_keyboards_labels_acpi_device_as_built_in():
    # Real-world case: the laptop's own keyboard, exactly as seen on this
    # project's own dev machine.
    connection = MagicMock()
    connection.query.return_value = [
        _fake_pnp_entity(
            name="Standard PS/2 Keyboard", manufacturer="(Standard keyboards)", device_id=r"ACPI\MSFT0003\0"
        )
    ]

    keyboards = _query_keyboards(connection, {})

    assert len(keyboards) == 1
    assert keyboards[0].name == "Standard PS/2 Keyboard"
    assert keyboards[0].is_built_in is True


def test_query_keyboards_labels_hid_and_usb_devices_as_external():
    # Real-world case: a plugged-in USB keyboard's keyboard-specific
    # interface is enumerated on the HID bus, not the USB bus directly —
    # this is why keyboards need their own PNPClass-filtered query rather
    # than reusing the USB-only one.
    connection = MagicMock()
    connection.query.return_value = [
        _fake_pnp_entity(
            name="HID Keyboard Device",
            manufacturer="(Standard keyboards)",
            device_id=r"HID\VID_0B05&PID_1A83&MI_03\7&28A3303E&0&0000",
        )
    ]

    keyboards = _query_keyboards(connection, {})

    assert len(keyboards) == 1
    assert keyboards[0].is_built_in is False


def test_query_keyboards_groups_sibling_interfaces_of_one_external_keyboard():
    connection = MagicMock()
    connection.query.return_value = [
        _fake_pnp_entity(
            name="HID Keyboard Device",
            manufacturer=None,
            device_id=r"HID\VID_0B05&PID_1A83&MI_00\7&303C4C75&0&0000",
        ),
        _fake_pnp_entity(
            name="HID Keyboard Device",
            manufacturer=None,
            device_id=r"HID\VID_0B05&PID_1A83&MI_03\7&28A3303E&0&0000",
        ),
    ]

    keyboards = _query_keyboards(connection, {})

    assert len(keyboards) == 1
    assert keyboards[0].is_built_in is False


def test_query_keyboards_degrades_to_empty_list_on_query_failure():
    connection = MagicMock()
    connection.query.side_effect = Exception("WMI query failed")

    assert _query_keyboards(connection, {}) == []


# --- keyboard/USB cross-referencing (a receiver's spare keyboard-capable
# interface shouldn't be double-counted as its own keyboard entry) ---


def test_query_keyboards_does_not_double_list_a_receivers_keyboard_capable_interface():
    # Real-world case this feature was built for: a Logitech LIGHTSPEED
    # receiver only paired to a mouse still exposes a keyboard-capable HID
    # interface, which showed up as an indistinguishable second
    # "HID Keyboard Device (EXTERNAL)" row alongside the user's actual
    # external keyboard. Since the receiver is already identified and
    # listed once in the USB section, its keyboard interface should be
    # dropped here rather than double-listed.
    usb_devices_by_key = {
        "VID_046D&PID_C54D": UsbDevice(
            name="LIGHTSPEED Receiver",
            manufacturer="Logitech",
            category="Wireless Mouse/Keyboard Receiver",
            interface_count=3,
            is_generic=False,
            is_built_in=None,
        )
    }
    connection = MagicMock()
    connection.query.return_value = [
        _fake_pnp_entity(
            name="HID Keyboard Device",
            manufacturer="(Standard keyboards)",
            device_id=r"HID\VID_046D&PID_C54D&MI_01&COL01\7&2D956586&0&0000",
        )
    ]

    keyboards = _query_keyboards(connection, usb_devices_by_key)

    assert keyboards == []


def test_query_keyboards_still_lists_an_unidentified_keyboard_sharing_a_vendor_with_a_generic_usb_entry():
    # A real external keyboard's own USB-bus wrapper row is often generic
    # and unrecognized by known_devices.py (e.g. "USB Composite Device"),
    # so it must NOT be suppressed the way an already-identified device's
    # spare interface is — but it should still get a better manufacturer
    # than the bare "(Standard keyboards)" placeholder via the vendor-ID
    # lookup, so it reads as something more useful than a second
    # indistinguishable "HID Keyboard Device".
    usb_devices_by_key = {
        "VID_0B05&PID_1A83": UsbDevice(
            name="USB Composite Device",
            manufacturer="(Standard USB Host Controller)",
            category=None,
            interface_count=4,
            is_generic=True,
            is_built_in=None,
        )
    }
    connection = MagicMock()
    connection.query.return_value = [
        _fake_pnp_entity(
            name="HID Keyboard Device",
            manufacturer="(Standard keyboards)",
            device_id=r"HID\VID_0B05&PID_1A83&MI_00\7&303C4C75&0&0000",
        )
    ]

    keyboards = _query_keyboards(connection, usb_devices_by_key)

    assert len(keyboards) == 1
    assert keyboards[0].manufacturer == "ASUS"


def test_index_usb_devices_by_hardware_key_maps_grouping_key_to_its_device():
    raw = [
        _RawPnpEntity(
            name="LIGHTSPEED Receiver", manufacturer="Logitech", device_id=r"USB\VID_046D&PID_C54D\3957336F3135"
        ),
    ]
    devices = _group_usb_devices(raw)

    index = _index_usb_devices_by_hardware_key(raw, devices)

    assert index == {"VID_046D&PID_C54D": devices[0]}


# --- monitors: built-in panel detection via Display Config API ---


def test_hardware_id_from_monitor_device_path_normalizes_hash_separators_and_prefix():
    path = "\\\\?\\DISPLAY#ACI27EA#4&39c00d2&0&UID4352#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}"
    assert _hardware_id_from_monitor_device_path(path) == "ACI27EA"
    assert _hardware_id_from_monitor_device_path(None) is None
    assert _hardware_id_from_monitor_device_path("") is None


def test_get_builtin_display_hardware_ids_matches_internal_output_technology_only():
    internal_path = _make_path_info(output_technology=_DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL, target_id=10)
    external_path = _make_path_info(output_technology=8, target_id=11)  # some non-internal connector type

    device_paths_by_target_id = {
        10: "\\\\?\\DISPLAY#ACI27EA#4&39c00d2&0&UID4352#{guid}",
        11: "\\\\?\\DISPLAY#GSM5B23#5&abc123&0&UID99#{guid}",
    }

    def fake_get_device_info(device_name_ptr):
        device_name = device_name_ptr.contents
        device_name.monitorDevicePath = device_paths_by_target_id[device_name.header.id]
        return 0  # ERROR_SUCCESS

    with patch(
        "src.collectors.device_inventory._query_display_config_paths",
        return_value=[internal_path, external_path],
    ), patch("src.collectors.device_inventory._user32") as mock_user32:
        mock_user32.DisplayConfigGetDeviceInfo.side_effect = fake_get_device_info
        result = _get_builtin_display_hardware_ids()

    assert result == {"ACI27EA"}


def test_get_builtin_display_hardware_ids_returns_none_when_api_unavailable():
    with patch("src.collectors.device_inventory._query_display_config_paths", return_value=[]):
        assert _get_builtin_display_hardware_ids() is None


def test_get_device_inventory_decodes_monitors_and_correlates_resolution():
    monitor_id = _fake_monitor_id(
        manufacturer_chars=_ascii_to_uint16_array("ACI", padded_length=4),
        model_chars=_ascii_to_uint16_array("ROG PG279Q", padded_length=14),
        instance_name=r"DISPLAY\ACI27EA\4&39c00d2&0&UID4352_0",
    )

    cimv2_connection = MagicMock()
    cimv2_connection.query.return_value = []

    wmi_namespace_connection = MagicMock()
    wmi_namespace_connection.WmiMonitorID.return_value = [monitor_id]

    def fake_wmi_ctor(*args, **kwargs):
        if kwargs.get("namespace") == "wmi":
            return wmi_namespace_connection
        return cimv2_connection

    with patch("src.collectors.device_inventory.wmi.WMI", side_effect=fake_wmi_ctor), patch(
        "src.collectors.device_inventory._get_monitor_resolutions_by_hardware_id",
        return_value={"ACI27EA": "2560x1440"},
    ), patch("src.collectors.device_inventory._get_builtin_display_hardware_ids", return_value={"ACI27EA"}):
        inventory = get_device_inventory()

    assert len(inventory.monitors) == 1
    monitor = inventory.monitors[0]
    assert monitor.manufacturer == "ACI"
    assert monitor.model == "ROG PG279Q"
    assert monitor.resolution == "2560x1440"
    assert monitor.is_built_in is True


def test_get_device_inventory_labels_external_monitor_as_not_built_in():
    monitor_id = _fake_monitor_id(
        manufacturer_chars=_ascii_to_uint16_array("LEN", padded_length=4),
        model_chars=_ascii_to_uint16_array("LEN T34w-20", padded_length=16),
        instance_name=r"DISPLAY\GSM5B23\5&abc&0&UID99",
    )

    cimv2_connection = MagicMock()
    cimv2_connection.query.return_value = []

    wmi_namespace_connection = MagicMock()
    wmi_namespace_connection.WmiMonitorID.return_value = [monitor_id]

    def fake_wmi_ctor(*args, **kwargs):
        if kwargs.get("namespace") == "wmi":
            return wmi_namespace_connection
        return cimv2_connection

    with patch("src.collectors.device_inventory.wmi.WMI", side_effect=fake_wmi_ctor), patch(
        "src.collectors.device_inventory._get_monitor_resolutions_by_hardware_id", return_value={}
    ), patch(
        "src.collectors.device_inventory._get_builtin_display_hardware_ids", return_value={"ACI27EA"}
    ):
        inventory = get_device_inventory()

    assert inventory.monitors[0].is_built_in is False


def test_get_device_inventory_leaves_monitor_built_in_none_when_display_config_api_unavailable():
    monitor_id = _fake_monitor_id(
        manufacturer_chars=_ascii_to_uint16_array("DEL", padded_length=4),
        model_chars=_ascii_to_uint16_array("U2720Q", padded_length=14),
        instance_name=r"DISPLAY\DELA0B1\5&abc&0&UID99",
    )

    cimv2_connection = MagicMock()
    cimv2_connection.query.return_value = []

    wmi_namespace_connection = MagicMock()
    wmi_namespace_connection.WmiMonitorID.return_value = [monitor_id]

    def fake_wmi_ctor(*args, **kwargs):
        if kwargs.get("namespace") == "wmi":
            return wmi_namespace_connection
        return cimv2_connection

    with patch("src.collectors.device_inventory.wmi.WMI", side_effect=fake_wmi_ctor), patch(
        "src.collectors.device_inventory._get_monitor_resolutions_by_hardware_id", return_value={}
    ), patch("src.collectors.device_inventory._get_builtin_display_hardware_ids", return_value=None):
        inventory = get_device_inventory()

    assert inventory.monitors[0].resolution is None
    assert inventory.monitors[0].is_built_in is None


def test_get_device_inventory_degrades_to_empty_monitors_when_wmi_namespace_unavailable():
    cimv2_connection = MagicMock()
    cimv2_connection.query.return_value = []

    def fake_wmi_ctor(*args, **kwargs):
        if kwargs.get("namespace") == "wmi":
            raise Exception("root\\wmi not available on this system")
        return cimv2_connection

    with patch("src.collectors.device_inventory.wmi.WMI", side_effect=fake_wmi_ctor):
        inventory = get_device_inventory()

    assert inventory.monitors == []


def test_get_device_inventory_degrades_entirely_when_wmi_totally_unavailable():
    with patch("src.collectors.device_inventory.wmi.WMI", side_effect=Exception("COM error")):
        inventory = get_device_inventory()

    assert inventory.usb_devices == []
    assert inventory.keyboards == []
    assert inventory.monitors == []

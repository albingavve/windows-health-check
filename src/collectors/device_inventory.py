"""Gathers currently-connected USB peripherals, keyboards, and monitors
via WMI plus a couple of targeted Win32 APIs.

Unlike system_specs.py, this data is NOT cached — a USB device, keyboard,
or monitor can be plugged/unplugged mid-session, so get_device_inventory()
queries fresh on every call. That's safe here specifically because, per
the API layer (server.py), this is only ever called on-demand (the
Devices popup's first open, plus its own manual refresh button) — never
on a continuous poll — so the cost isn't paid repeatedly the way it would
be if this were wired into the live-stats polling loop.

Each device category is queried independently and degrades to an empty
list on failure rather than aborting the whole response, same pattern as
system_specs.py — WMI classes here (WmiMonitorID in particular, which
lives outside the default namespace and isn't present on every system)
and the Win32 Display Config API can be unavailable on some configs.
"""

import ctypes
import re
import winreg
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import asdict, dataclass

import pythoncom
import pywintypes
import win32api
import win32con
import wmi

from src.collectors.known_devices import lookup_known_device, lookup_vendor_by_id


@dataclass
class UsbDevice:
    name: str
    manufacturer: str | None
    # From known_devices.py's lookup; None when unrecognized (never
    # fabricated).
    category: str | None
    # How many Win32_PnPEntity rows collapsed into this one physical
    # device — see _group_pnp_entities_by_hardware_id(). 1 for an
    # ordinary single-interface device; only interesting when > 1.
    interface_count: int
    # True => generic bus/hub/controller plumbing rather than a distinct
    # peripheral (see _is_generic_plumbing()) — the frontend tucks these
    # into a collapsed "System & Hub Devices" section.
    is_generic: bool
    # Best-effort signal from the device's LocationInformation registry
    # value (see _read_location_information()) — True only when a
    # driver-supplied hint like "Integrated" or "Internal" is actually
    # found. None (never False) otherwise: this property isn't
    # consistently populated by every manufacturer, so its absence just
    # means "unknown", not "definitely external".
    is_built_in: bool | None


@dataclass
class Keyboard:
    name: str
    manufacturer: str | None
    # Deterministic, unlike UsbDevice.is_built_in above: True when the
    # device's PNP enumerator is ACPI (the laptop's own internal bus)
    # rather than USB/HID (plugged in) — see _query_keyboards().
    is_built_in: bool


@dataclass
class Monitor:
    manufacturer: str | None
    model: str | None
    # "WIDTHxHEIGHT", or None when it couldn't be reliably correlated to a
    # WmiMonitorID entry (see _get_monitor_resolutions_by_hardware_id) —
    # left blank rather than guessed.
    resolution: str | None
    # True when the Windows Display Config API reports this display's
    # connector as DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL (a built-in
    # panel); False when the API succeeded but this monitor specifically
    # wasn't reported that way; None only if the API itself was entirely
    # unavailable/failed (see _get_builtin_display_hardware_ids()).
    is_built_in: bool | None


@dataclass
class DeviceInventory:
    usb_devices: list[UsbDevice]
    keyboards: list[Keyboard]
    monitors: list[Monitor]

    def to_dict(self) -> dict:
        return asdict(self)


@contextmanager
def _com_initialized():
    """Ensure COM is initialized on the calling thread — see
    system_specs.py's identical helper for why (FastAPI's worker threads
    don't have COM initialized by default). Duplicated rather than
    imported so each collector module stays independent of the others.
    """
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


@dataclass
class _RawPnpEntity:
    name: str
    manufacturer: str | None
    device_id: str


def _query_pnp_entities(connection: "wmi.WMI", where_clause: str) -> list[_RawPnpEntity]:
    """Run a targeted WQL SELECT + WHERE against Win32_PnPEntity, filtered
    to only currently-present devices (Status == "OK"). Shared by both the
    USB and keyboard queries below.

    Deliberately never the bare Win32_PnPEntity() call other collectors
    use for other classes: unfiltered, that fetches *every* property of
    *every* PnP device on the system (often 1000+ entries) and was
    measured taking 30+ seconds — a well-documented WMI performance trap
    for this particular class.
    """
    try:
        entities = connection.query(
            f"SELECT Name, Manufacturer, DeviceID, Status FROM Win32_PnPEntity WHERE {where_clause}"
        )
    except Exception:
        return []

    raw: list[_RawPnpEntity] = []
    for entity in entities:
        if getattr(entity, "Status", None) != "OK":
            continue
        name = getattr(entity, "Name", None)
        device_id = getattr(entity, "DeviceID", None)
        if not name or not device_id:
            continue
        raw.append(_RawPnpEntity(name=name, manufacturer=getattr(entity, "Manufacturer", None), device_id=device_id))
    return raw


_VID_PID_PATTERN = re.compile(r"VID_[0-9A-F]{4}&PID_[0-9A-F]{4}", re.IGNORECASE)
_VID_PATTERN = re.compile(r"VID_([0-9A-F]{4})", re.IGNORECASE)


def _pnp_grouping_key(device_id: str) -> str:
    """Extract a grouping key identifying the *physical device* behind a
    PNP DeviceID, rather than one specific logical interface.

    A composite device (e.g. a wireless receiver that exposes several HID
    collections) enumerates as multiple Win32_PnPEntity rows that share
    the same enumerator + vendor/product ID but each add their own
    interface-index suffix and their own unique instance ID after the
    second backslash — e.g. "USB\\VID_046D&PID_405E&MI_00\\6&2d...0" and
    "USB\\VID_046D&PID_405E&MI_02\\6&2d...2" are two interfaces of the
    very same physical receiver. Matching the leading "VID_xxxx&PID_xxxx"
    prefix of the hardware-ID segment (and ignoring everything after it,
    plus the instance-ID segment entirely) collapses these back to one
    shared key ("VID_046D&PID_405E") without guessing based on display
    name — matching on name alone would incorrectly merge unrelated
    devices that share a generic name like "USB Input Device".

    Originally this only stripped a literal "&MI_XX" suffix, which missed
    other real composite-interface suffixes — confirmed on this project's
    own dev machine, where a Logitech LIGHTSPEED receiver's extra "Lamp
    Array" RGB-lighting interfaces enumerate as
    "USB\\VID_046D&PID_C54D&LAMPARRAY\\...", not "&MI_XX". That suffix
    survived the old stripping logic untouched, so those rows grouped
    under a different key than the receiver's own
    "USB\\VID_046D&PID_C54D\\..." row and the receiver showed up twice.
    Matching on the VID/PID prefix instead of stripping a specific known
    suffix handles that case and any other composite-interface suffix
    Windows uses (e.g. "&COL01") without needing to enumerate them all.

    Devices with no VID/PID in their hardware ID (e.g. "ACPI\\MSFT0003\\0",
    used for built-in keyboards) fall back to the full hardware-ID segment
    unchanged, same as before.
    """
    parts = device_id.split("\\")
    if len(parts) < 2:
        return device_id
    hardware_id = parts[1]
    match = _VID_PID_PATTERN.match(hardware_id)
    if match:
        return match.group(0).upper()
    return hardware_id


def _extract_vid(hardware_key: str) -> str | None:
    """Pull the 4-hex-digit vendor ID out of a grouping key/hardware ID
    (e.g. "VID_046D&PID_C54D" -> "046D"), for known_devices.py's
    vendor-ID lookup. None when there isn't one (e.g. an ACPI device)."""
    match = _VID_PATTERN.search(hardware_key)
    return match.group(1).upper() if match else None


# Name patterns that unambiguously identify generic bus/hub/controller
# plumbing rather than a distinct peripheral. Deliberately conservative —
# only kinds Windows itself consistently names this way, so an
# unrecognized-but-real peripheral never gets hidden by mistake.
_GENERIC_USB_NAME_PATTERNS = ["root hub", "usb hub", "composite device", "root router", "usb input device"]


def _looks_like_generic_name(name: str) -> bool:
    name_lower = name.lower()
    return any(pattern in name_lower for pattern in _GENERIC_USB_NAME_PATTERNS)


def _is_placeholder_manufacturer(manufacturer: str | None) -> bool:
    """True for Windows' own placeholder manufacturer strings for an
    inbox/generic-class driver (e.g. "(Standard keyboards)",
    "(Standard system devices)") — a reliable "this isn't the real vendor"
    signal, unlike a simply-missing manufacturer, which isn't strong
    enough on its own to justify hiding or overriding anything."""
    return bool(manufacturer) and manufacturer.startswith("(Standard")


def _is_generic_plumbing(name: str, manufacturer: str | None) -> bool:
    """True for generic USB infrastructure (hubs, root routers, composite-
    device wrapper entries, bare unlabeled input devices) that belongs in
    the collapsed "System & Hub Devices" section rather than the primary
    peripheral list. Only called for devices known_devices.py didn't
    already recognize — a known match always wins."""
    if _looks_like_generic_name(name):
        return True
    if _is_placeholder_manufacturer(manufacturer):
        return True
    return False


def _pick_representative_member(members: list[_RawPnpEntity]) -> _RawPnpEntity:
    """Pick which sibling interface's name/manufacturer represents the
    whole physical device.

    A composite device commonly enumerates a generically-named wrapper
    row (e.g. "USB Composite Device") *alongside* a specifically-named
    interface row (e.g. "ROG PELTA (2.4GHz)") under the same hardware ID —
    which one WMI happens to return first isn't meaningful. Preferring
    the first sibling whose name doesn't look generic means the specific,
    recognizable name wins regardless of enumeration order; falls back to
    the first member if every sibling looks generic (e.g. an actual hub
    with no specifically-named part).
    """
    for member in members:
        if not _looks_like_generic_name(member.name):
            return member
    return members[0]


def _group_pnp_entities_by_hardware_id(raw_entities: list[_RawPnpEntity]) -> list[list[_RawPnpEntity]]:
    """Collapse raw Win32_PnPEntity rows into groups sharing one physical
    device's hardware ID (see _pnp_grouping_key), preserving first-seen
    order."""
    groups: dict[str, list[_RawPnpEntity]] = {}
    order: list[str] = []
    for entity in raw_entities:
        key = _pnp_grouping_key(entity.device_id)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(entity)
    return [groups[key] for key in order]


# Substrings actually seen in real driver-supplied LocationInformation
# values for internal/integrated peripherals (e.g. laptop webcam INFs
# commonly set this to something like "Integrated Camera"). Deliberately
# NOT treated as authoritative on its own — this registry value isn't
# consistently populated by every manufacturer, so an unrecognized value,
# or its absence, just means "unknown" here, never "definitely external".
_BUILTIN_LOCATION_HINTS = ["internal", "integrated"]


def _read_location_information(device_id: str) -> str | None:
    """Best-effort read of a PnP device's LocationInformation registry
    value (HKLM\\SYSTEM\\CurrentControlSet\\Enum\\<DeviceID>) — the
    modern equivalent of the classic SPDRP_LOCATION_INFORMATION device
    property. Many drivers never populate this at all; it's read purely
    as an opportunistic hint, never as something authoritative."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Enum\{device_id}") as key:
            value, _value_type = winreg.QueryValueEx(key, "LocationInformation")
    except OSError:
        return None
    return value or None


def _looks_built_in_from_location(location_information: str | None) -> bool | None:
    if not location_information:
        return None
    location_lower = location_information.lower()
    if any(hint in location_lower for hint in _BUILTIN_LOCATION_HINTS):
        return True
    return None


def _group_usb_devices(raw_entities: list[_RawPnpEntity]) -> list[UsbDevice]:
    """Collapse raw Win32_PnPEntity rows into one UsbDevice per physical
    device, apply the known_devices.py lookup, and classify each as
    primary or generic plumbing."""
    devices: list[UsbDevice] = []
    for members in _group_pnp_entities_by_hardware_id(raw_entities):
        representative = _pick_representative_member(members)
        name = representative.name
        # Prefer the representative's own manufacturer; only fall back to
        # a sibling's if the representative itself didn't report one.
        manufacturer = representative.manufacturer or next((m.manufacturer for m in members if m.manufacturer), None)

        category, manufacturer_override = lookup_known_device(name, manufacturer)
        if not manufacturer and manufacturer_override:
            manufacturer = manufacturer_override

        is_generic = category is None and _is_generic_plumbing(name, manufacturer)
        is_built_in = _looks_built_in_from_location(_read_location_information(representative.device_id))

        devices.append(
            UsbDevice(
                name=name,
                manufacturer=manufacturer,
                category=category,
                interface_count=len(members),
                is_generic=is_generic,
                is_built_in=is_built_in,
            )
        )
    return devices


def _index_usb_devices_by_hardware_key(
    raw_entities: list[_RawPnpEntity], usb_devices: list[UsbDevice]
) -> dict[str, UsbDevice]:
    """Map each already-built UsbDevice back to its grouping key (see
    _pnp_grouping_key), so _query_keyboards can recognize when a
    keyboard-capable HID interface actually belongs to a device already
    listed in the USB section — e.g. a Logitech LIGHTSPEED receiver
    commonly exposes a keyboard-capable HID interface even when only a
    mouse is paired to it — instead of double-listing that same physical
    device as a second, generic "HID Keyboard Device" entry.

    `usb_devices` must be `_group_usb_devices(raw_entities)`'s own return
    value for the same `raw_entities` — the two are matched up positionally
    by re-running the same grouping (cheap: at most a few dozen rows).
    """
    groups = _group_pnp_entities_by_hardware_id(raw_entities)
    return {_pnp_grouping_key(group[0].device_id): device for group, device in zip(groups, usb_devices)}


def _resolve_keyboard_manufacturer(
    raw_manufacturer: str | None, hardware_key: str, matched_usb_device: UsbDevice | None
) -> str | None:
    """Best-effort real manufacturer for a keyboard entry, preferring a
    more specific identity than Windows' own generic placeholder strings
    (e.g. "(Standard keyboards)") when one can be found — first from a
    matched USB device's own already-resolved manufacturer (e.g. "Logitech"
    for a LIGHTSPEED receiver), then a vendor-ID-prefix lookup
    (known_devices.lookup_vendor_by_id, e.g. "0B05" -> "ASUS"), falling
    back to whatever Windows itself reported rather than fabricating
    anything."""
    if (
        matched_usb_device is not None
        and matched_usb_device.manufacturer
        and not _is_placeholder_manufacturer(matched_usb_device.manufacturer)
    ):
        return matched_usb_device.manufacturer
    vendor_override = lookup_vendor_by_id(_extract_vid(hardware_key))
    if vendor_override:
        return vendor_override
    return raw_manufacturer


def _query_keyboards(connection: "wmi.WMI", usb_devices_by_key: dict[str, UsbDevice]) -> list[Keyboard]:
    """Keyboards, both built-in and external, identified via WMI's
    PNPClass='Keyboard' — a separate, targeted query from the USB-only one
    above, because a USB/wireless keyboard's actual keyboard-identifying
    interface is enumerated on the HID bus ("HID\\..."), not the USB bus
    directly (the composite USB device's own "USB\\..." row is usually
    just a generic wrapper), and a built-in laptop keyboard is enumerated
    on the ACPI bus ("ACPI\\...") and would never match a USB-prefixed
    query at all. Filtering on PNPClass rather than parsing DeviceID
    prefixes means both cases are found the same way, structurally.

    is_built_in is decided purely by DeviceID enumerator: "ACPI\\" means
    the laptop's own internal bus; anything else ("USB\\", "HID\\") means
    it was plugged in.

    `usb_devices_by_key` (see _index_usb_devices_by_hardware_key) lets a
    keyboard-capable HID interface be recognized as belonging to a device
    already listed in the USB section — a Logitech LIGHTSPEED receiver in
    particular commonly exposes one even when only a mouse is paired to
    it, which otherwise shows up as an indistinguishable second "HID
    Keyboard Device" entry alongside a real external keyboard. When that
    happens the interface is attributed back to the matched device instead
    of listed a second time; an unrecognized keyboard sharing a vendor ID
    with a plain (uncategorized) USB entry is still listed, just with a
    best-effort vendor-derived manufacturer (see
    _resolve_keyboard_manufacturer) instead of a bare generic one.
    """
    raw = _query_pnp_entities(connection, "PNPClass='Keyboard'")

    keyboards: list[Keyboard] = []
    for members in _group_pnp_entities_by_hardware_id(raw):
        representative = _pick_representative_member(members)
        hardware_key = _pnp_grouping_key(representative.device_id)
        matched_usb_device = usb_devices_by_key.get(hardware_key)

        # Already shown once as its identified USB device (e.g. the
        # LIGHTSPEED receiver itself) — don't list this interface again.
        if matched_usb_device is not None and matched_usb_device.category is not None:
            continue

        raw_manufacturer = representative.manufacturer or next((m.manufacturer for m in members if m.manufacturer), None)
        manufacturer = _resolve_keyboard_manufacturer(raw_manufacturer, hardware_key, matched_usb_device)
        is_built_in = representative.device_id.upper().startswith("ACPI\\")
        keyboards.append(Keyboard(name=representative.name, manufacturer=manufacturer, is_built_in=is_built_in))
    return keyboards


def _decode_edid_string(values) -> str | None:
    """Decode a WmiMonitorID string field.

    These fields (ManufacturerName, UserFriendlyName, ...) look like byte
    arrays but are actually arrays of UInt16, one ASCII character code
    per element, NUL-padded to a fixed length — a well-known WMI
    monitor-query gotcha. Naively treating them as raw bytes produces
    garbage; this decodes each element as a character and drops the NUL
    padding.
    """
    if not values:
        return None
    text = "".join(chr(v) for v in values if v != 0).strip()
    return text or None


def _extract_hardware_id(pnp_id: str | None) -> str | None:
    """PNP device/instance IDs are backslash-separated:
    `<enumerator>\\<hardware id>\\<instance id>`, e.g.
    "DISPLAY\\ACI27EA\\4&39c00d2&0&UID4352_0". The middle segment is the
    same hardware ID whether it comes from WmiMonitorID's InstanceName,
    EnumDisplayDevices' monitor DeviceID, or the Display Config API's
    monitorDevicePath (see _hardware_id_from_monitor_device_path), and is
    the only reliable (non-guessing) way to correlate them.
    """
    if not pnp_id:
        return None
    parts = pnp_id.split("\\")
    return parts[1] if len(parts) > 1 else None


# Sane upper bound on adapters to walk — EnumDisplayDevices has no fixed
# limit, but real hardware never comes close to this.
_MAX_DISPLAY_ADAPTERS = 16


def _get_monitor_resolutions_by_hardware_id() -> dict[str, str]:
    """Best-effort {hardware_id: "WIDTHxHEIGHT"} map, built by walking
    active display adapters via win32api and matching each one's monitor
    sub-device hardware ID against WmiMonitorID's InstanceName (see
    _extract_hardware_id). A monitor whose hardware ID can't be resolved
    this way is simply left without a resolution rather than guessed at
    or mismatched to a different monitor's numbers.

    Returns {} entirely (never a partially-wrong map) if win32api
    enumeration itself fails — e.g. no attached displays, or running in
    an environment without a display subsystem.
    """
    resolutions: dict[str, str] = {}
    try:
        for adapter_index in range(_MAX_DISPLAY_ADAPTERS):
            try:
                adapter = win32api.EnumDisplayDevices(None, adapter_index)
            except pywintypes.error:
                break
            if adapter is None:
                break
            if not (adapter.StateFlags & win32con.DISPLAY_DEVICE_ATTACHED_TO_DESKTOP):
                continue

            try:
                monitor = win32api.EnumDisplayDevices(adapter.DeviceName, 0)
            except pywintypes.error:
                continue
            hardware_id = _extract_hardware_id(getattr(monitor, "DeviceID", None)) if monitor else None
            if not hardware_id:
                continue

            try:
                settings = win32api.EnumDisplaySettings(adapter.DeviceName, win32con.ENUM_CURRENT_SETTINGS)
            except pywintypes.error:
                continue
            if settings is None:
                continue

            resolutions[hardware_id] = f"{settings.PelsWidth}x{settings.PelsHeight}"
    except Exception:
        return {}
    return resolutions


# --- Windows Display Config API (ctypes) — used only to determine which
# monitor(s) are built-in panels (DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL).
# Not wrapped by pywin32, so this calls user32.dll directly. Struct layouts
# below match the documented wingdi.h definitions exactly (verified against
# Microsoft Learn, not guessed) — a wrong field order/size here wouldn't
# error, it would silently misread memory, so precision matters more than
# usual.

_QDC_ONLY_ACTIVE_PATHS = 0x00000002
_DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2
_DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL = 0x80000000
_ERROR_SUCCESS = 0
_ERROR_INSUFFICIENT_BUFFER = 122

# Module-level (rather than fetched fresh inside each function) so tests
# can patch this one seam instead of the global ctypes.windll singleton.
_user32 = ctypes.windll.user32


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wintypes.UINT), ("Denominator", wintypes.UINT)]


class _DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", _LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("statusFlags", wintypes.UINT),
    ]


class _DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", _LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("outputTechnology", wintypes.UINT),
        ("rotation", wintypes.UINT),
        ("scaling", wintypes.UINT),
        ("refreshRate", _DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", wintypes.UINT),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", wintypes.UINT),
    ]


class _DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", _DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", _DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", wintypes.UINT),
    ]


class _DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    # The real struct's last member is a union of several mode-info types
    # we never need to read ourselves (we only need modeInfoArray to exist
    # as correctly-sized scratch space for QueryDisplayConfig to write
    # into) — represented as opaque bytes rather than fully modeled.
    _fields_ = [
        ("infoType", wintypes.UINT),
        ("id", wintypes.UINT),
        ("adapterId", _LUID),
        ("_opaque_mode_union", ctypes.c_byte * 48),
    ]


class _DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.UINT),
        ("size", wintypes.UINT),
        ("adapterId", _LUID),
        ("id", wintypes.UINT),
    ]


class _DISPLAYCONFIG_TARGET_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", _DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("flags", wintypes.UINT),
        ("outputTechnology", wintypes.UINT),
        ("edidManufactureId", wintypes.USHORT),
        ("edidProductCodeId", wintypes.USHORT),
        ("connectorInstance", wintypes.UINT),
        ("monitorFriendlyDeviceName", wintypes.WCHAR * 64),
        ("monitorDevicePath", wintypes.WCHAR * 128),
    ]


def _query_display_config_paths() -> list[_DISPLAYCONFIG_PATH_INFO]:
    """Wraps GetDisplayConfigBufferSizes + QueryDisplayConfig for
    QDC_ONLY_ACTIVE_PATHS, retrying if the display configuration changes
    between the two calls (the buffer-size race the Microsoft reference
    implementation itself retries on)."""
    path_count = wintypes.UINT(0)
    mode_count = wintypes.UINT(0)

    for _attempt in range(5):
        result = _user32.GetDisplayConfigBufferSizes(
            _QDC_ONLY_ACTIVE_PATHS, ctypes.pointer(path_count), ctypes.pointer(mode_count)
        )
        if result != _ERROR_SUCCESS:
            return []

        paths = (_DISPLAYCONFIG_PATH_INFO * path_count.value)()
        modes = (_DISPLAYCONFIG_MODE_INFO * mode_count.value)()
        result = _user32.QueryDisplayConfig(
            _QDC_ONLY_ACTIVE_PATHS,
            ctypes.pointer(path_count),
            paths,
            ctypes.pointer(mode_count),
            modes,
            None,
        )
        if result == _ERROR_SUCCESS:
            return list(paths)[: path_count.value]
        if result != _ERROR_INSUFFICIENT_BUFFER:
            return []
    return []


def _hardware_id_from_monitor_device_path(monitor_device_path: str | None) -> str | None:
    """monitorDevicePath looks like
    "\\\\?\\DISPLAY#ACI27EA#4&39c00d2&0&UID4352#{guid}" — '#'-separated
    instead of '\\'-separated, with a leading "\\\\?\\" volume-style
    prefix. Normalizing both lets _extract_hardware_id apply here too."""
    if not monitor_device_path:
        return None
    normalized = monitor_device_path.removeprefix("\\\\?\\").replace("#", "\\")
    return _extract_hardware_id(normalized)


def _get_builtin_display_hardware_ids() -> set[str] | None:
    """Best-effort set of PNP hardware IDs (see _extract_hardware_id) for
    displays the Windows Display Config API reports as
    DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL — Windows' own structural
    signal for "this output is a built-in panel" (eDP/internal), as
    opposed to guessing from manufacturer/model naming.

    Returns None (distinct from an empty set) if the Display Config API
    itself is unavailable/failed — a real desktop session always has at
    least one active display path, so zero paths means the query didn't
    work, not "zero monitors". An empty *set* means the API worked but
    found no internal display (a legitimate all-external-monitor setup).
    The caller reports is_built_in as None (unknown) only in the None
    case — False (known external) is still a confident answer once the
    API has actually run.
    """
    try:
        paths = _query_display_config_paths()
    except Exception:
        return None
    if not paths:
        return None

    hardware_ids: set[str] = set()
    for path in paths:
        if path.targetInfo.outputTechnology != _DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL:
            continue

        device_name = _DISPLAYCONFIG_TARGET_DEVICE_NAME()
        device_name.header.type = _DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME
        device_name.header.size = ctypes.sizeof(_DISPLAYCONFIG_TARGET_DEVICE_NAME)
        device_name.header.adapterId = path.targetInfo.adapterId
        device_name.header.id = path.targetInfo.id

        try:
            result = _user32.DisplayConfigGetDeviceInfo(ctypes.pointer(device_name))
        except Exception:
            continue
        if result != _ERROR_SUCCESS:
            continue

        hardware_id = _hardware_id_from_monitor_device_path(device_name.monitorDevicePath)
        if hardware_id:
            hardware_ids.add(hardware_id)
    return hardware_ids


def _query_monitors(wmi_namespace_connection: "wmi.WMI") -> list[Monitor]:
    try:
        monitor_ids = wmi_namespace_connection.WmiMonitorID()
    except Exception:
        return []

    resolutions_by_hardware_id = _get_monitor_resolutions_by_hardware_id()
    builtin_hardware_ids = _get_builtin_display_hardware_ids()

    monitors: list[Monitor] = []
    for monitor_id in monitor_ids:
        manufacturer = _decode_edid_string(getattr(monitor_id, "ManufacturerName", None))
        model = _decode_edid_string(getattr(monitor_id, "UserFriendlyName", None))
        hardware_id = _extract_hardware_id(getattr(monitor_id, "InstanceName", None))
        resolution = resolutions_by_hardware_id.get(hardware_id) if hardware_id else None

        if builtin_hardware_ids is None:
            is_built_in = None
        else:
            is_built_in = bool(hardware_id and hardware_id in builtin_hardware_ids)

        monitors.append(Monitor(manufacturer=manufacturer, model=model, resolution=resolution, is_built_in=is_built_in))
    return monitors


_EMPTY_DEVICE_INVENTORY = DeviceInventory(usb_devices=[], keyboards=[], monitors=[])

# Generous, but bounded: in every isolated test run during development
# (FastAPI's TestClient, a plain background thread, a plain
# multiprocessing.Process, and even a multiprocessing child spawned from
# an asyncio executor thread — the same mechanism this project's own dev-
# server reload wrapper uses) the full collection consistently completed
# in under 3 seconds. But it was also observed, specifically and only
# through the actual running dev server's real request-handling thread,
# taking far longer with no clear cause found despite investigation.
# Rather than leave that unresolved mystery able to hang a real request
# indefinitely, this bounds it: on timeout, every field degrades to
# empty — the same fallback already used for outright WMI failures.
_DEVICE_INVENTORY_TIMEOUT_SECONDS = 8.0


def _collect_device_inventory() -> DeviceInventory:
    """The actual (potentially slow) collection work — see
    get_device_inventory(), which wraps this with a timeout."""
    try:
        with _com_initialized():
            connection = wmi.WMI()
            # Deliberately does NOT attempt to report USB-A vs USB-C port
            # type: Windows doesn't reliably expose physical connector type
            # through Win32_PnPEntity (or any standard device API) — the
            # device's own DeviceID/PNP class describes what it *is*, not
            # which port shape it's plugged into — so this is omitted
            # entirely rather than guessed at.
            usb_raw_entities = _query_pnp_entities(connection, "DeviceID LIKE 'USB%'")
            usb_devices = _group_usb_devices(usb_raw_entities)
            usb_devices_by_key = _index_usb_devices_by_hardware_key(usb_raw_entities, usb_devices)
            keyboards = _query_keyboards(connection, usb_devices_by_key)

            try:
                wmi_namespace_connection = wmi.WMI(namespace="wmi")
                monitors = _query_monitors(wmi_namespace_connection)
            except Exception:
                # root\wmi (WmiMonitorID's namespace) isn't present on
                # every system — degrade to no monitor data rather than
                # losing the USB/keyboard results already gathered above.
                monitors = []
    except Exception:
        usb_devices, keyboards, monitors = [], [], []

    return DeviceInventory(usb_devices=usb_devices, keyboards=keyboards, monitors=monitors)


def get_device_inventory() -> DeviceInventory:
    """Return currently-connected USB devices, keyboards, and monitors —
    queried fresh every call (see module docstring for why no caching).
    See _DEVICE_INVENTORY_TIMEOUT_SECONDS above for why this is bounded
    by a hard timeout rather than calling _collect_device_inventory()
    directly."""
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_collect_device_inventory)
    try:
        return future.result(timeout=_DEVICE_INVENTORY_TIMEOUT_SECONDS)
    except Exception:
        return _EMPTY_DEVICE_INVENTORY
    finally:
        # wait=False: never block the response on a call that may itself
        # be the thing that's hanging — let it finish (or not) in the
        # background rather than waiting for it here.
        executor.shutdown(wait=False)

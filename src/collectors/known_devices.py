"""Lookup table mapping common USB-peripheral name/manufacturer patterns
to a friendly category label — same spirit as known_software.py: a small,
hand-curated table of matched patterns, honest fallback to "leave it
unmatched" rather than guessing at what an unrecognized device actually
is.

Matching is a case-insensitive substring match against a combination of
the device's `name` and `manufacturer` (mirrors
known_software.lookup_known_software()'s name+command approach) — some
categories only show up reliably in one field or the other for a given
device (see the ROG entry below, where "audio" typically only appears in
the reported manufacturer string, not the product name).
"""

KNOWN_DEVICES: list[dict] = [
    {
        "matches": ["lightspeed"],
        "category": "Wireless Mouse/Keyboard Receiver",
        # LIGHTSPEED is Logitech's wireless-receiver brand, used for both
        # mice and keyboards. The receiver itself doesn't expose which
        # specific peripheral(s) are paired to it, or a model number —
        # deliberately not guessed at. Windows also frequently reports no
        # Manufacturer at all for this device's logical sub-interfaces,
        # which is what "manufacturer" below fills in (only ever used to
        # fill a blank, never to override what Windows did report).
        "manufacturer": "Logitech",
    },
    {
        "matches": ["uvc webcam", "usb video device", "webcam"],
        "category": "Webcam",
    },
    {
        # "rog" alone is too broad to safely call "a headset" — ASUS ROG
        # branding covers motherboards, laptops, mice, monitors, etc. Both
        # "rog" and "audio" must appear (name and/or manufacturer) before
        # this counts as a match.
        "matches": ["rog"],
        "requires": ["audio"],
        "category": "Headset/Audio",
    },
    {
        "matches": ["bluetooth"],
        "category": "Bluetooth Adapter",
    },
]


def lookup_known_device(name: str, manufacturer: str | None = None) -> tuple[str | None, str | None]:
    """Look up (category, manufacturer_override) for a USB device.

    Returns (None, None) when nothing matches, rather than guessing — see
    known_software.lookup_known_software() for the identical philosophy.
    `manufacturer_override` is only ever used to fill in a manufacturer
    Windows itself reported as blank; it never overrides a manufacturer
    Windows *did* report, since that could be genuinely different for a
    rebadged/OEM product and this table has no way to know that.
    """
    haystack = f"{name} {manufacturer or ''}".lower()
    for entry in KNOWN_DEVICES:
        if not any(match in haystack for match in entry["matches"]):
            continue
        if "requires" in entry and not all(req in haystack for req in entry["requires"]):
            continue
        return entry["category"], entry.get("manufacturer")
    return None, None


# USB vendor-ID (the 4 hex digits after "VID_" in a PNP hardware ID) to
# manufacturer name, for devices/interfaces that don't carry a usable name
# or manufacturer string of their own — notably a HID keyboard interface,
# which Windows commonly reports only as a bare "HID Keyboard Device" with
# manufacturer "(Standard keyboards)", giving device_inventory.py no way to
# tell two such entries apart. Deliberately tiny and hand-curated, same
# spirit as KNOWN_DEVICES above: only IDs actually seen and confirmed, never
# a large scraped vendor-ID database.
KNOWN_VENDOR_IDS: dict[str, str] = {
    "046D": "Logitech",
    "0B05": "ASUS",
}


def lookup_vendor_by_id(vendor_id: str | None) -> str | None:
    """Look up a manufacturer name from a USB vendor ID (e.g. "046D").

    Returns None when the ID is missing or unrecognized, rather than
    guessing — same honesty guarantee as lookup_known_device() above.
    """
    if not vendor_id:
        return None
    return KNOWN_VENDOR_IDS.get(vendor_id.upper())

from src.collectors.known_devices import lookup_known_device


def test_lookup_known_device_matches_lightspeed_and_fills_in_manufacturer():
    category, manufacturer = lookup_known_device("LIGHTSPEED Receiver", manufacturer=None)
    assert category == "Wireless Mouse/Keyboard Receiver"
    assert manufacturer == "Logitech"


def test_lookup_known_device_matches_webcam_pattern():
    category, manufacturer_override = lookup_known_device("USB2.0 HD UVC WebCam", manufacturer="Microsoft")
    assert category == "Webcam"
    # Windows already reported a manufacturer — nothing to override.
    assert manufacturer_override is None


def test_lookup_known_device_matches_bluetooth_pattern():
    category, _ = lookup_known_device("Intel(R) Wireless Bluetooth(R)", manufacturer="Intel Corporation")
    assert category == "Bluetooth Adapter"


def test_lookup_known_device_requires_both_rog_and_audio_terms():
    # "audio" shows up in the manufacturer string here, not the name —
    # matching must consider both fields combined.
    category, _ = lookup_known_device("ROG PELTA (2.4GHz)", manufacturer="(Generic USB Audio)")
    assert category == "Headset/Audio"

    # "rog" alone (e.g. an unrelated ROG-branded component) must not match.
    no_match_category, _ = lookup_known_device("ROG Strix Motherboard Sensor", manufacturer=None)
    assert no_match_category is None


def test_lookup_known_device_is_case_insensitive():
    category, manufacturer = lookup_known_device("lightspeed receiver", manufacturer=None)
    assert category == "Wireless Mouse/Keyboard Receiver"
    assert manufacturer == "Logitech"

    bluetooth_category, _ = lookup_known_device("INTEL BLUETOOTH RADIO", manufacturer=None)
    assert bluetooth_category == "Bluetooth Adapter"


def test_lookup_known_device_returns_none_none_for_unmatched():
    category, manufacturer = lookup_known_device("Some Random Peripheral", manufacturer="Some Corp")
    assert category is None
    assert manufacturer is None

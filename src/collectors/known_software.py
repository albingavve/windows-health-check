"""Lookup table mapping common startup/service names to a plain-English
description and an estimated startup impact.

Matching is a case-insensitive substring match against both the item's
`name` and its `command`. Impact ratings are general estimates based on the
program's typical behavior — not measurements of any specific machine.

This table is deliberately small and hand-curated. Add entries as new
software is encountered; unmatched items should stay unlabeled rather than
guessing (see `lookup_known_software`).
"""

KNOWN_SOFTWARE: list[dict[str, list[str] | str]] = [
    # --- Chat / communication apps ---
    {
        "matches": ["discord"],
        "description": "Discord is a voice/text chat app popular with gamers and communities; it auto-launches to speed up opening the app but isn't required to run at startup.",
        "impact": "medium",
    },
    {
        "matches": ["slack"],
        "description": "Slack is a team messaging app that starts at login so you don't miss notifications; safe to disable if you don't need it running immediately after boot.",
        "impact": "medium",
    },
    {
        "matches": ["teams"],
        "description": "Microsoft Teams is a workplace chat/video app known for a heavy startup footprint; generally safe to disable and launch manually when needed.",
        "impact": "high",
    },
    {
        "matches": ["zoom"],
        "description": "Zoom is a video conferencing app; its startup entry mainly preloads for faster meeting joins and can be disabled without losing functionality.",
        "impact": "low",
    },
    # --- Game launchers ---
    {
        "matches": ["steam"],
        "description": "Steam is Valve's game launcher/store client; it starts at login to keep games updated and enable overlay features, but can be launched manually instead.",
        "impact": "medium",
    },
    {
        "matches": ["epicgameslauncher", "epic games launcher"],
        "description": "Epic Games Launcher is the client for the Epic Games Store; it isn't needed at startup unless you want games ready to launch immediately.",
        "impact": "medium",
    },
    {
        "matches": ["eadm", "ea desktop", "eabackgroundservice"],
        "description": "EA Desktop (formerly Origin) is EA's game launcher; its background service isn't needed unless you're actively playing an EA game.",
        "impact": "medium",
    },
    {
        "matches": ["ubisoft connect", "upc.exe", "uplay"],
        "description": "Ubisoft Connect is Ubisoft's game launcher and overlay service; safe to disable at startup and launch on demand.",
        "impact": "medium",
    },
    {
        "matches": ["galaxyclient", "gog galaxy"],
        "description": "GOG Galaxy is a lightweight game launcher for GOG.com; its startup impact is minor but can still be disabled if unused.",
        "impact": "low",
    },
    {
        "matches": ["battle.net", "battlenet"],
        "description": "Battle.net is Blizzard's game launcher and updater; not required at startup unless you want Blizzard games ready immediately.",
        "impact": "medium",
    },
    # --- Cloud sync ---
    {
        "matches": ["onedrive"],
        "description": "OneDrive is Microsoft's cloud file sync client; disabling it at startup only pauses automatic syncing until you open it manually.",
        "impact": "low",
    },
    {
        "matches": ["dropbox"],
        "description": "Dropbox is a cloud file sync client; it's lightweight at startup but can be disabled if you sync infrequently.",
        "impact": "low",
    },
    {
        "matches": ["google drive", "googledrivesync"],
        "description": "Google Drive is a cloud file sync client; safe to disable at startup and open manually when you need to sync files.",
        "impact": "low",
    },
    {
        "matches": ["icloud"],
        "description": "iCloud is Apple's cloud sync client for Windows; safe to disable at startup if you don't need continuous syncing with Apple devices.",
        "impact": "low",
    },
    # --- Creative / dev tools ---
    {
        "matches": ["adobe", "creative cloud"],
        "description": "Adobe Creative Cloud's background helper checks for app updates and licensing; it's known for a heavy startup footprint and is generally safe to disable, launching Creative Cloud manually instead.",
        "impact": "high",
    },
    {
        "matches": ["jetbrains toolbox"],
        "description": "JetBrains Toolbox manages installs/updates for JetBrains IDEs; lightweight at startup, but safe to disable if you don't need automatic IDE updates.",
        "impact": "low",
    },
    {
        "matches": ["lm studio", "lmstudio"],
        "description": "LM Studio is a desktop app for running local large language models; it has no need to run at startup unless you use it immediately after boot.",
        "impact": "medium",
    },
    {
        "matches": ["docker desktop", "docker.exe", "com.docker"],
        "description": "Docker Desktop runs a background VM/engine for containers, which is resource-heavy; disable at startup and launch it only when you need containers running.",
        "impact": "high",
    },
    {
        "matches": ["mathworks", "matlab"],
        "description": "MathWorks/MATLAB startup entries are typically license-manager or update helpers; low overhead, but not needed unless you use MATLAB regularly.",
        "impact": "low",
    },
    # --- Peripherals ---
    {
        "matches": ["razer"],
        "description": "Razer Synapse configures Razer peripherals (lighting, macros, DPI); it needs to run for those settings to apply, but can be disabled if you don't rely on custom peripheral profiles.",
        "impact": "medium",
    },
    {
        "matches": ["lghub", "lg hub", "logitech g hub"],
        "description": "Logitech G HUB configures Logitech gaming peripherals; it's known for high memory/CPU use at startup and is safe to disable if you don't need live lighting/macro profiles.",
        "impact": "high",
    },
    {
        "matches": ["nvidia geforce experience", "nvidia broadcast", "geforcenow"],
        "description": "NVIDIA GeForce Experience/Broadcast provide driver updates, game optimization, and streaming features; can be disabled at startup without affecting core GPU driver function.",
        "impact": "medium",
    },
    {
        "matches": ["icue", "corsair"],
        "description": "Corsair iCUE controls Corsair peripherals and RGB lighting; it's known for a heavy startup footprint and can be disabled if you don't need live lighting/fan-curve control.",
        "impact": "high",
    },
    # --- VPN ---
    {
        "matches": ["nordvpn"],
        "description": "NordVPN's client auto-starts so a VPN connection can reconnect automatically; safe to disable if you prefer to connect manually.",
        "impact": "low",
    },
    {
        "matches": ["expressvpn"],
        "description": "ExpressVPN's client auto-starts to support auto-connect on boot; safe to disable if you connect manually instead.",
        "impact": "low",
    },
    # --- Known Windows telemetry / system services ---
    {
        "matches": ["diagtrack", "connected user experiences and telemetry"],
        "description": "Diagnostics Tracking Service (DiagTrack) collects usage/diagnostic data sent to Microsoft; disabling it reduces telemetry but won't affect core Windows functionality for most users.",
        "impact": "low",
    },
    {
        "matches": ["wsearch", "windows search"],
        "description": "Windows Search indexes files for fast Start-menu and File Explorer search; disabling it saves some background CPU/disk use but makes searches slower.",
        "impact": "medium",
    },
    {
        "matches": ["sysmain", "superfetch"],
        "description": "SysMain (formerly Superfetch) preloads frequently used apps into memory to speed up launch times; can be disabled on systems with an SSD where its benefit is minimal.",
        "impact": "medium",
    },
    {
        "matches": ["waasmedicsvc", "windows update medic"],
        "description": "Windows Update Medic Service repairs Windows Update components and resists being disabled; it's a core system service best left alone.",
        "impact": "low",
    },
]


def lookup_known_software(name: str, command: str) -> tuple[str | None, str | None]:
    """Look up a plain-English description and estimated impact for a startup item.

    Matches case-insensitively against a combination of `name` and `command`.
    Returns (None, None) when nothing matches, rather than guessing.
    """
    haystack = f"{name} {command}".lower()
    for entry in KNOWN_SOFTWARE:
        if any(match in haystack for match in entry["matches"]):
            return entry["description"], entry["impact"]
    return None, None

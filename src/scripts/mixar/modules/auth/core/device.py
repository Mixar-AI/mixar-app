# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Stable, privacy-preserving device identifier.

Sent to the backend at login, SSO token exchange, and the agent WebSocket
handshake as an anti-abuse signal (one free trial per machine). The raw OS
machine identifier never leaves this module — only a truncated SHA-256 of
it is sent. If no OS identifier is available, a random id is generated once
and persisted in the Mixar config file.

All failure paths return None: the device id is best-effort and must never
break login or connection flows.
"""

import hashlib
import re
import subprocess
import sys
import uuid

from ....config.config import add_config, get_config
from ....config.logging_config import get_logger

logger = get_logger(__name__)

# Domain-separation prefix so the hash can't be matched against digests of
# the same machine id computed by other software.
_NAMESPACE = "mixar-device-v1"

_DEVICE_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")

_cached_device_id = None


def _windows_machine_guid():
    """HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid — stable per OS install."""
    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Cryptography",
        0,
        winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
    )
    try:
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        return value
    finally:
        winreg.CloseKey(key)


def _macos_platform_uuid():
    """IOPlatformUUID — stable per machine."""
    output = subprocess.run(
        ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', output)
    return match.group(1) if match else None


def _linux_machine_id():
    """systemd/dbus machine-id — stable per OS install."""
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r") as f:
                value = f.read().strip()
            if value:
                return value
        except OSError:
            continue
    return None


def _raw_machine_identifier():
    try:
        if sys.platform == "win32":
            return _windows_machine_guid()
        if sys.platform == "darwin":
            return _macos_platform_uuid()
        return _linux_machine_id()
    except Exception as e:
        logger.debug("Machine identifier unavailable: %s", e)
        return None


def _fallback_persisted_id():
    """Random id persisted in mixar.json when no OS identifier is readable."""
    try:
        existing = get_config().get("device_id")
        if isinstance(existing, str) and _DEVICE_ID_RE.match(existing):
            return existing
        generated = uuid.uuid4().hex
        add_config("device_id", generated)
        return generated
    except Exception as e:
        logger.debug("Persisted device id unavailable: %s", e)
        return None


def get_device_id():
    """Return the hashed device id, or None if unavailable.

    Cached for the process lifetime — the underlying identifiers are
    immutable while Blender runs.
    """
    global _cached_device_id
    if _cached_device_id:
        return _cached_device_id

    raw = _raw_machine_identifier()
    if raw:
        digest = hashlib.sha256(
            f"{_NAMESPACE}:{raw.strip().lower()}".encode("utf-8")
        ).hexdigest()[:32]
        _cached_device_id = digest
        return digest

    _cached_device_id = _fallback_persisted_id()
    return _cached_device_id

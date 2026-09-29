# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The running build's version as the ``X-Client-Version`` request header.

The backend's force-update gate (``require_supported_client``) judges a
request by this header first and only falls back to ``users.client_version``
— last-writer-wins across every install sharing the account — when it is
absent. Without it one outdated machine on a shared login gets every other
machine refused as outdated (and an updated one can lift the refusal for an
outdated one).

The value comes from ``update_checker.get_runtime_version`` — the same
source as the agent WebSocket handshake's ``addon_version`` and
``PUT /me/client-version`` — so the three can never disagree. An unknown
version (dev build, stock Blender) omits the header instead of sending a
placeholder. Safe to call from any thread; never raises.
"""

from typing import Dict, Optional

CLIENT_VERSION_HEADER = "X-Client-Version"

# The binary's version cannot change while it runs. Only a known version is
# cached: an early call may run before the version is resolvable.
_cached_version: Optional[str] = None


def get_client_version() -> Optional[str]:
    """The running build's version, or None when it is unknown."""
    global _cached_version
    if _cached_version:
        return _cached_version
    try:
        from ..updates.core.update_checker import get_runtime_version

        version = get_runtime_version()
    except Exception:
        return None
    if version:
        _cached_version = version
    return version or None


def client_version_headers() -> Dict[str, str]:
    """``{"X-Client-Version": <version>}``, or ``{}`` when it is unknown."""
    version = get_client_version()
    return {CLIENT_VERSION_HEADER: version} if version else {}

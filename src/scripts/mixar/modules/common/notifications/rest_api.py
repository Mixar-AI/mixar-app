# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Notifications REST API helpers

Wraps the /api/v1/notifications REST endpoints:
  PUT  /me/client-version — report the addon version (and hashed device id)
                            to the server
"""

from typing import Dict, Optional

import requests

from mixar.config.logging_config import get_logger

from .constants import NOTIFICATIONS_REST_PATH

logger = get_logger(__name__)

_DEFAULT_TIMEOUT = 10.0


def _url(host: str, path: str) -> str:
    return f"{host}{NOTIFICATIONS_REST_PATH}{path}"


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def report_client_version(
    host: str,
    token: str,
    client_version: str,
    device_id: Optional[str] = None,
) -> bool:
    """PUT /me/client-version — returns True on success.

    ``device_id`` is the hashed id from ``auth.core.device.get_device_id()``
    (same value as the agent WS handshake); the backend upserts it into a
    per-device table. Omitted from the body when unavailable.
    """
    payload = {"client_version": client_version}
    if device_id:
        payload["device_id"] = device_id
    try:
        resp = requests.put(
            _url(host, "/me/client-version"),
            headers=_headers(token),
            json=payload,
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") == "success":
            logger.info(f"Reported client version {client_version}")
            return True
        logger.warning(f"report_client_version failed: {body.get('message')}")
    except Exception as e:
        logger.error(f"report_client_version error: {e}")
    return False

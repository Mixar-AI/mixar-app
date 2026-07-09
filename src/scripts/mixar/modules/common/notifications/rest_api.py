# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Notifications REST API helpers

Wraps the /api/v1/notifications REST endpoints:
  PUT  /me/client-version — report the addon version to the server
"""

from typing import Dict

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
) -> bool:
    """PUT /me/client-version — returns True on success."""
    try:
        resp = requests.put(
            _url(host, "/me/client-version"),
            headers=_headers(token),
            json={"client_version": client_version},
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

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Headers for the auth module's raw ``requests`` calls.

The auth flows (login, refresh, me, handoff, SSO token exchange, guest) run
before or outside ``HTTPClient``, so they build their headers by hand. They
still need the build's ``X-Client-Version``: a backend blue/green deploy
routes a client version to the fleet built for it by that header, and a
sign-in that lands on the other fleet would be the one request path that
can disagree with the rest of the app. Never raises.
"""
from typing import Dict, Optional


def auth_headers(
    *, json_body: bool = False, bearer: Optional[str] = None, **extra: str
) -> Dict[str, str]:
    """``accept`` plus, as requested, a JSON content type, a bearer token,
    any extra header, and the build's version when it is known."""
    headers: Dict[str, str] = {"accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    headers.update(extra)
    try:
        from ...common.api.client_version import client_version_headers
        headers.update(client_version_headers())
    except Exception:  # noqa: BLE001 — advisory header, never blocks auth
        pass
    return headers

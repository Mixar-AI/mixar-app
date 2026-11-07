# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP client for MatGen catalog and script fetching.

Generation is handled by the unified generation queue.
Catalog/script fetch functions run in daemon threads.
"""
import queue
import threading
from typing import Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

_CATALOG_TIMEOUT = 10   # seconds — catalog/script fetches; fail fast


def _auth_headers(auth_token: str) -> dict:
    """Bearer auth plus ``X-Client-Version``: the mat-gen router sits behind
    the backend's force-update gate, which judges that header first."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    try:
        from ...common.api.client_version import client_version_headers

        headers.update(client_version_headers())
    except Exception:
        pass
    return headers


def fetch_catalog_async(
    auth_token: str,
    base_url: str,
    result_queue: queue.Queue,
) -> None:
    """Fetch the server-side procedural material catalog.

    Designed to run in a daemon thread. Puts exactly one item in result_queue:
    {"ok": True, "materials": [...]} or {"ok": False, "error": "..."}.
    Each material dict has: material_id, name, category, source, thumbnail_url.
    """
    if requests is None:
        result_queue.put({"ok": False, "error": "requests library not available"})
        return

    url = f"{base_url.rstrip('/')}/api/v1/mat-gen/catalog"
    headers = _auth_headers(auth_token)

    try:
        response = requests.get(url, headers=headers, timeout=_CATALOG_TIMEOUT)
        try:
            payload = response.json()
        except Exception:
            result_queue.put({"ok": False, "error": f"HTTP {response.status_code}: non-JSON response"})
            return

        if not response.ok:
            msg = payload.get("message") or payload.get("detail") or f"HTTP {response.status_code}"
            result_queue.put({"ok": False, "error": msg})
            return

        if payload.get("status") == "success":
            d = payload.get("data", {})
            result_queue.put({"ok": True, "materials": d.get("materials", [])})
        else:
            msg = payload.get("message") or f"HTTP {response.status_code}"
            result_queue.put({"ok": False, "error": msg})

    except Exception as exc:  # noqa: BLE001
        result_queue.put({"ok": False, "error": str(exc)})


def fetch_script_async(
    material_id: str,
    auth_token: str,
    base_url: str,
    result_queue: queue.Queue,
) -> None:
    """Fetch a single material's Python script from the server.

    Designed to run in a daemon thread. Puts exactly one item in result_queue:
    {"ok": True, "script": "...", "name": "..."} or {"ok": False, "error": "..."}.
    """
    if requests is None:
        result_queue.put({"ok": False, "error": "requests library not available"})
        return

    url = f"{base_url.rstrip('/')}/api/v1/mat-gen/script/{material_id}"
    headers = _auth_headers(auth_token)

    try:
        response = requests.get(url, headers=headers, timeout=_CATALOG_TIMEOUT)
        try:
            payload = response.json()
        except Exception:
            result_queue.put({"ok": False, "error": f"HTTP {response.status_code}: non-JSON response"})
            return

        if not response.ok:
            msg = payload.get("message") or payload.get("detail") or f"HTTP {response.status_code}"
            result_queue.put({"ok": False, "error": msg})
            return

        if payload.get("status") == "success":
            d = payload.get("data", {})
            result_queue.put({"ok": True, "script": d.get("script", ""), "name": d.get("name", "")})
        else:
            msg = payload.get("message") or f"HTTP {response.status_code}"
            result_queue.put({"ok": False, "error": msg})

    except Exception as exc:  # noqa: BLE001
        result_queue.put({"ok": False, "error": str(exc)})


def fetch_script_blocking(
    material_id: str,
    auth_token: str,
    base_url: str,
) -> str | None:
    """Fetch a material script synchronously and return the script text.

    Called on the main thread when the user clicks 'Add to Layer'.
    Returns the script string on success, or None on any failure.
    """
    if requests is None:
        return None

    url = f"{base_url.rstrip('/')}/api/v1/mat-gen/script/{material_id}"
    headers = _auth_headers(auth_token)

    try:
        response = requests.get(url, headers=headers, timeout=_CATALOG_TIMEOUT)
        if not response.ok:
            return None
        payload = response.json()
        if payload.get("status") == "success":
            return payload.get("data", {}).get("script") or None
    except Exception:  # noqa: BLE001
        pass
    return None

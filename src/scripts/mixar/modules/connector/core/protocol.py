# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP path routing for the Mixar connector sidecar (no bpy)."""

from __future__ import annotations

import hmac
import json
from typing import Any
from urllib.parse import urlparse

ALLOWED_FORMATS = {"usd", "fbx", "glb"}
#: Largest JSON body the sidecar reads; every route carries a small spec.
MAX_BODY = 1024 * 1024


def request_rejection(headers: Any, port: int, token: str) -> tuple[int, str] | None:
    """Why a request may not be served, as ``(status, message)``, or ``None``.

    Browsers send ``Origin`` on every cross-site request, so its presence means
    a web page, never the hub. The ``Host`` check defeats DNS rebinding (a
    hostname an attacker points at 127.0.0.1 arrives with that hostname), and
    the bearer token keeps every other local process out: the sidecar is bound
    to loopback, but loopback is shared by every user process on the machine.
    """
    if headers.get("Origin") or headers.get("Host") != "127.0.0.1:%d" % port:
        return 403, "Only the local Mixar hub may connect"
    supplied = headers.get("Authorization") or ""
    # Bytes, not str: compare_digest raises on a non-ASCII header value.
    expected = ("Bearer " + token).encode("utf-8")
    if not token or not hmac.compare_digest(supplied.encode("utf-8", "replace"), expected):
        return 401, "Local connector credential rejected; restart the hub"
    return None


def parse_export_body(raw: bytes | str) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8") if raw else "{}"
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("export body must be a JSON object")
    fmt = str(payload.get("format") or "usd").lower().lstrip(".")
    if fmt in {"usda", "usdc", "usdz"}:
        fmt = "usd"
    if fmt not in ALLOWED_FORMATS:
        raise ValueError(f"unsupported format {fmt!r}; expected usd, fbx, or glb")
    destination = str(payload.get("destination") or "unreal").lower()
    if destination not in {"unreal", "file"}:
        raise ValueError("destination must be unreal or file")
    object_names = payload.get("object_names") or []
    if object_names and not isinstance(object_names, list):
        raise ValueError("object_names must be a list")
    return {
        "format": fmt,
        "destination": destination,
        "object_names": [str(name) for name in object_names],
        "unreal_destination": str(payload.get("unreal_destination") or "/Game/Mixar/Imports"),
        "actor_label": str(payload.get("actor_label") or "MixarScene"),
    }


def sidecar_routes() -> dict[str, tuple[str, ...]]:
    return {
        "GET": ("/health", "/scene", "/moodboard", "/moodboard/{index}/preview",
                "/viewport.png", "/viewport.jpg"),
        "POST": ("/export", "/prompt", "/heartbeat"),
    }


def is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}

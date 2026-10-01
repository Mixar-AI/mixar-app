# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP path routing for the Mixar connector sidecar (no bpy)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

ALLOWED_FORMATS = {"usd", "fbx", "glb"}


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
        "GET": ("/health", "/scene", "/moodboard", "/viewport.jpg"),
        "POST": ("/export", "/prompt", "/heartbeat"),
        "OPTIONS": ("*",),
    }


def is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}

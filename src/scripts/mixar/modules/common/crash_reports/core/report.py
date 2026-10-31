# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build the wire report (``docs/api/frontend/crash-reports.md`` in the backend).

Every string in the returned payload has been through ``scrub``: no local path,
user name, e-mail or report-log content leaves the machine.
"""

from __future__ import annotations

import hashlib
import traceback
from datetime import datetime, timezone

from ..constants import MAX_FRAMES, MAX_MESSAGE_CHARS, MAX_RAW_CHARS
from .scrub import python_file, scrub_crash_text, scrub_text, scrub_value

_CONTEXT_KEYS = (
    "gpu_vendor", "gpu_renderer", "gpu_driver", "gpu_backend", "cycles_device",
    "cycles_scene_device", "render_engine", "open_tabs", "agent_session_id", "agent_run_id",
    "app_session_id", "cpu_arch", "cpu_count", "ram_gb", "model",
)


def report_id_for(kind: str, key: str) -> str:
    return hashlib.sha256(f"{kind}:{key}".encode("utf-8", errors="replace")).hexdigest()[:32]


def _context(static: dict, session: dict | None, current: dict, parsed: dict | None = None) -> dict:
    merged: dict = {}
    for source in (static, current, session or {}, parsed or {}):
        for key in _CONTEXT_KEYS:
            value = source.get(key)
            if value not in (None, ""):
                merged[key] = value
    merged["reporter_app_version"] = current.get("app_version")
    merged["context_source"] = "session" if session else "reporter"
    return {key: value for key, value in merged.items() if value is not None}


def native_report(
    parsed: dict,
    *,
    source: str,
    report_id: str,
    device_id: str,
    crashed_at: datetime | None,
    static: dict,
    session: dict | None,
    current: dict,
    raw_text: str | None,
) -> dict:
    """A crash file (crash.txt or .ips) as a wire report."""
    session_ctx = (session or {}).get("context", {}) if session else None
    app_version = parsed.get("app_version") or (session_ctx or {}).get("app_version")
    payload = {
        "report_id": report_id,
        "device_id": device_id,
        "kind": "native",
        "source": source,
        "crashed_at": (parsed.get("crashed_at")
                       or (crashed_at.astimezone(timezone.utc).isoformat() if crashed_at else None)),
        "app_version": app_version,
        "blender_version": parsed.get("blender_version") or (session_ctx or {}).get("blender_version"),
        "build_hash": parsed.get("build_hash"),
        "platform": parsed.get("platform") or static.get("platform"),
        "os_version": parsed.get("os_version") or static.get("os_version"),
        "crash_type": parsed.get("crash_type"),
        "crash_module": parsed.get("crash_module"),
        "thread": parsed.get("thread"),
        "frames": parsed.get("frames", [])[:MAX_FRAMES],
        "python_frames": parsed.get("python_frames", [])[:MAX_FRAMES],
        "operators": parsed.get("operators", []),
        "git_sha": parsed.get("git_sha"),
        "arch": parsed.get("arch"),
        "images": parsed.get("images") or [],
        "context": _context(static, session_ctx, current, parsed),
    }
    payload = scrub_value({key: value for key, value in payload.items() if value is not None})
    if raw_text:
        payload["raw_text"] = scrub_crash_text(raw_text)[:MAX_RAW_CHARS]
    return payload


def exception_report(
    exc_type,
    exc,
    tb,
    *,
    source: str,
    device_id: str | None,
    static: dict,
    current: dict,
) -> dict:
    """An uncaught Python exception as a wire report (``device_id`` filled at send)."""
    frames = []
    for frame in reversed(traceback.extract_tb(tb, limit=MAX_FRAMES)):
        frames.append({
            "file": python_file(frame.filename),
            "function": str(frame.name)[:128],
            "line": frame.lineno or 0,
        })
    type_name = f"{getattr(exc_type, '__module__', '')}.{getattr(exc_type, '__qualname__', 'Exception')}"
    if type_name.startswith("builtins."):
        type_name = type_name[len("builtins."):]
    try:
        message = str(exc)
    except Exception:  # noqa: BLE001 - a broken __str__ must not break reporting
        message = ""
    key = "|".join([type_name] + [f"{f['file']}:{f['function']}" for f in frames[:3]])
    payload = {
        "report_id": report_id_for("python", key + "|" + datetime.now(timezone.utc).isoformat()),
        "device_id": device_id or "",
        "kind": "python",
        "source": source,
        "crashed_at": datetime.now(timezone.utc).isoformat(),
        "app_version": current.get("app_version"),
        "blender_version": current.get("blender_version"),
        "platform": static.get("platform"),
        "os_version": static.get("os_version"),
        "crash_type": type_name[:128],
        "message": scrub_text(message)[:MAX_MESSAGE_CHARS],
        "python_frames": frames,
        "context": {**_context(static, None, current), "context_source": "live"},
    }
    payload["_dedup_key"] = key
    return scrub_value({k: v for k, v in payload.items() if v is not None})

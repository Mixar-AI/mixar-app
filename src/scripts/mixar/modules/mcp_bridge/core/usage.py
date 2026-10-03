# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Content-free ``mcp.tool_called`` events for the tools Mixar serves locally.

The backend reports the scene tools it serves (``surface: backend``); the
interface, scene-tab and project tools never reach it, so the desktop reports
them (``surface: desktop``) through its consent-gated analytics. Same event,
same ``agent_source: mcp`` as BYOK's vocabulary. Never arguments or results.
The client-name table mirrors the backend's ``modules/mcp/usage_signals.py``;
keep them in step.
"""

import re
import time

#: Substring -> normalised name; first match wins ("cursor-vscode" is Cursor).
_CLIENTS = (
    ("claude-code", "claude-code"), ("codex", "codex"), ("cursor", "cursor"),
    ("opencode", "opencode"), ("windsurf", "windsurf"), ("cline", "cline"),
    ("gemini", "gemini-cli"), ("zed", "zed"), ("visual studio code", "vscode"),
    ("vscode", "vscode"), ("claude", "claude-desktop"), ("continue", "continue"),
)
_VERSION = re.compile(r"^[0-9][0-9A-Za-z.+-]{0,23}$")


def client_of(meta):
    info = meta.get("mixar/client") if isinstance(meta, dict) else None
    if not isinstance(info, dict):
        return "direct", ""
    raw = str(info.get("name") or "").strip().lower()[:80]
    name = next((label for key, label in _CLIENTS if key in raw), "other" if raw else "direct")
    version = str(info.get("version") or "")
    return name, version if _VERSION.match(version) else ""


def _kind(tool):
    return "ui" if str(tool).startswith("mixar_ui_") else "scene_tab"


def _status(result):
    if not result.get("isError"):
        return "ok"
    payload = (result.get("structuredContent") or {}).get("result") or {}
    return str(payload.get("error_type") or "error")[:32]


def report(tool, meta, session, result, started):
    """Called on the relay thread: capture on Blender's main thread, fail open."""
    try:
        import bpy
        from mixar.modules.common.analytics.capture import capture
        from mixar.modules.common.analytics.constants import EVENT_MCP_TOOL
        client, version = client_of(meta)
        properties = {
            "agent_source": "mcp", "surface": "desktop", "mcp_client": client,
            "mcp_client_version": version or None, "tool": str(tool)[:64], "tool_kind": _kind(tool),
            "status": _status(result), "duration_ms": int((time.monotonic() - started) * 1000),
            "scene_session_id": str(session)[:64] or None,
        }

        def emit():
            capture(EVENT_MCP_TOOL, properties)

        bpy.app.timers.register(emit, first_interval=0.0)
    except Exception:  # noqa: BLE001 - analytics must never affect a tool call
        pass

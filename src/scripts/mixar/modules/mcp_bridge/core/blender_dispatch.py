# SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dispatch bridge for the vendored Blender MCP handler surface.

Translates an incoming ``/api/{category}/{action}`` request into the vendored
Blender handler router. The router self-marshals onto Blender's main thread
via the Mixar-adapted ``blender.utils.queue`` shim (which delegates to
``executor_bridge.run_on_main_thread_sync``), so no extra threading is done
here — this is a thin lazy-import seam that also keeps handler registration
(which happens at import time) off the startup path until the first Blender
tool call.

It also enforces the raw-python-exec opt-out **server-side**: the ``python/
exec`` routes run non-sandboxed Python, and the gate must hold no matter which
client path reaches them (the Node ``blender_advanced_tool`` proxy can build
the route directly, bypassing any per-tool client check). This is the
authoritative gate; the Node side only adds early, friendly rejection.
"""

import os

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_DISABLED = {"0", "false", "no", "off"}

# Routes that execute raw (non-sandboxed) Python on the main thread. Gated by
# MIXAR_MCP_ALLOW_PYTHON_EXEC (default enabled — the bridge is a full-control,
# token-gated, loopback-only surface). Category/action pairs, lower-cased.
_PYTHON_EXEC_ROUTES = {("python", "exec"), ("python", "exec-file")}
_ENV_ALLOW_PYTHON_EXEC = "MIXAR_MCP_ALLOW_PYTHON_EXEC"


def _python_exec_allowed() -> bool:
    return os.environ.get(_ENV_ALLOW_PYTHON_EXEC, "1").strip().lower() not in _DISABLED


def _parse_route(path: str):
    """Return (category, action) for ``/api/{category}/{action}`` or None."""
    parts = path.strip("/").split("/")
    if len(parts) >= 3 and parts[0] == "api":
        return parts[1].lower(), parts[2].lower()
    return None


def dispatch_blender(path: str, params: dict) -> dict:
    """Route ``/api/{category}/{action}`` to the vendored Blender handlers.

    Returns the handler's envelope (``{success, data}`` or
    ``{success: false, error}``) verbatim, matching what the Node MCP
    server's blender-bridge client expects.
    """
    route = _parse_route(path)
    if route in _PYTHON_EXEC_ROUTES and not _python_exec_allowed():
        return {
            "success": False,
            "error": "Raw Python execution is disabled ({0}=0). Use the sandboxed "
            "mixar_execute_script instead.".format(_ENV_ALLOW_PYTHON_EXEC),
        }

    try:
        # Lazy import: triggers handler registration on first use only.
        from ..blender.handlers import route_request as blender_route
    except Exception as exc:  # import/registration failure must not 500 silently
        # Log full detail locally; return a generic message (import errors can
        # embed local filesystem paths).
        logger.error("[MCP bridge] Blender handler import failed: %s", exc, exc_info=True)
        return {
            "success": False,
            "error": "Blender handler surface unavailable (see Mixar log for details).",
        }

    return blender_route(path, params)

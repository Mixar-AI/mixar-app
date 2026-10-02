# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Main-thread snapshots for the opt-in local MCP connector."""

import threading
import uuid

import bpy

from mixar.config.config import get_config, get_server_url
from mixar.config.logging_config import get_logger

_logger = get_logger(__name__)
_snapshot = {}
_lock = threading.Lock()
_server = None
_registered = False
_provisioned = None


def snapshot():
    with _lock:
        return dict(_snapshot)


def enabled():
    return get_config().get("mcp_enabled") is True


def ui_control_enabled():
    """Opt-in: AI apps may observe and drive Mixar's interface (mixar_ui_observe/act/wait)."""
    return enabled() and get_config().get("mcp_ui_control") is True


def _tick():
    global _snapshot, _server, _provisioned
    try:
        from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager
        from mixar.modules.space_mixie_chat.core.session import get_session_manager
        from mixar.modules.common.api.client_version import client_version_headers
        from mixar.modules.common.analytics.preferences import is_enabled
        from mixar.modules.common.i18n import ui_locale
        manager = get_connection_manager()
        scene = bpy.context.scene
        if enabled() and scene and not getattr(scene, "mixie_session_id", ""):
            scene.mixie_session_id = str(uuid.uuid4())
        current = {
            "instance_id": get_session_manager().instance_id,
            "session_id": getattr(scene, "mixie_session_id", ""),
            "scene_name": getattr(scene, "name", ""),
            "connected": manager.is_connected,
            "ui_control": ui_control_enabled(),
            "signed_in": bool(getattr(bpy.context.window_manager, "mixie_chat_is_logged_in", False))
                         and not bool(getattr(bpy.context.window_manager, "mixie_chat_session_expired", False)),
            "backend_url": get_server_url(),
            "headers": {**client_version_headers(), "X-Mixar-Locale": ui_locale(),
                        "x-telemetry-consent": "1" if is_enabled() else "0"},
        }
        from . import eligibility
        from mixar.modules.common.ui_control.core import service
        if enabled():
            service.register()
            eligibility.refresh(current)
        else:
            eligibility.invalidate()
            service.invalidate()
        if _provisioned != enabled():
            from . import setup
            setup.connection_config("CODEX", bpy.utils.resource_path('LOCAL'), bpy.app.binary_path,
                                    enabled=enabled())
            _provisioned = enabled()
        if hasattr(bpy.context.window_manager, "mixar_ui_enable"):
            bpy.context.window_manager.mixar_ui_enable(enabled=enabled())
            current.update(ui_contract="mixar_ui_v1", ui_eligible=eligibility.valid())
        with _lock:
            _snapshot = current
        if enabled() and current["instance_id"] and _server is None:
            from .relay import RelayServer
            from .forward import forward
            candidate = RelayServer(snapshot, forward)
            try:
                candidate.start()
            except Exception:
                candidate.server_close()
                raise
            _server = candidate
        elif not enabled() and _server:
            from .lease import invalidate, tick
            invalidate()
            tick()
            _stop_server()
    except Exception as exc:
        _logger.debug("MCP connector waiting for desktop readiness: %s", type(exc).__name__)
    return 1.0 if _registered else None


def register():
    global _registered
    if _registered:
        return
    _registered = True
    bpy.app.timers.register(_tick, first_interval=3.0, persistent=True)


def unregister(shutdown=False):
    global _registered, _server
    _registered = False
    from . import eligibility
    from mixar.modules.common.ui_control.core import service
    eligibility.invalidate()
    service.unregister(shutdown=shutdown)
    try:
        _stop_server()
    finally:
        if not shutdown and bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)


def _stop_server():
    global _server
    server, _server = _server, None
    if server:
        server.stop()


def refresh():
    """Apply the user's connector preference immediately on the main thread."""
    _tick()


def is_running():
    return _server is not None

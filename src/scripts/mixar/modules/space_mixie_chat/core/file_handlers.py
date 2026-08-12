# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
File load handlers for Mixie Chat agent session cleanup.

Registers a bpy.app.handlers.load_pre handler that aborts any running
agent session when a new file is opened. This prevents agent tasks from
the previous file from continuing to execute in the new file context.

Also registers a load_post handler that sanitizes persisted chat enums:
.blend files saved by builds with since-removed enum items (e.g. the old
ASK chat mode, stored as int 2) would otherwise spam
"current value '2' matches no enum" bpy.rna warnings on every redraw.
"""

import threading

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

from ..constants import SessionState

logger = get_logger(__name__)


def _send_abort_request(session_id: str) -> None:
    """Send abort request to backend (runs in background thread)."""
    try:
        import httpx
        from mixar.config.config import get_server_url

        base_url = get_server_url()

        from .message_helpers import get_auth_token
        auth_token = get_auth_token()

        if not auth_token:
            logger.warning("No auth token available for file-load abort request")
            return

        url = f"{base_url}/api/v1/blender/agent/cancel"
        headers = {"Authorization": f"Bearer {auth_token}"}
        payload = {"session_id": session_id}

        with httpx.Client(timeout=5.0) as client:
            response = client.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                logger.info(
                    "Backend session aborted on file load: %s", session_id[:8]
                )
            else:
                logger.warning(
                    "Failed to abort backend session on file load: HTTP %d",
                    response.status_code,
                )
    except Exception as e:
        logger.error("Failed to send abort request on file load: %s", e)


@persistent
def _on_load_pre(*_args) -> None:
    """Abort all running agent sessions before a new file is loaded.

    Iterates all scenes and aborts any that have active sessions.
    """
    import bpy
    from .export_destination import clear_all_destinations
    from .session import get_session_manager

    clear_all_destinations()

    session = get_session_manager()

    # Collect session IDs from active scenes before cleanup
    active_session_ids = []
    for scene in bpy.data.scenes:
        state = session.get_state(scene)
        if state in (SessionState.BUSY, SessionState.MODIFYING,
                     SessionState.AWAITING_INPUT):
            sid = session.get_session_id(scene)
            if sid:
                active_session_ids.append(sid)
            session.set_state(scene, SessionState.IDLE)

    if not active_session_ids:
        logger.debug("load_pre: no active agent sessions, no abort needed")
        return

    logger.info(
        f"load_pre: aborting {len(active_session_ids)} active agent session(s)"
    )

    # Stop all SSE streams
    from .sse_handler import cleanup_all_sse_handlers
    cleanup_all_sse_handlers()

    # Flush queued tool scripts
    from .main_thread_executor import cleanup as flush_executor_queue
    flush_executor_queue()

    # Clean up the SSE event queue and timer
    from .queue_processor import cleanup_sse_queue
    cleanup_sse_queue()

    # Stop loader animations
    from .animation_manager import stop_loader_animation
    stop_loader_animation()

    # End any active agent turn in the executor
    from .executor import get_executor
    get_executor().end_agent_turn()

    # Send abort requests to backend for all active sessions
    for session_id in active_session_ids:
        thread = threading.Thread(
            target=_send_abort_request,
            args=(session_id,),
            daemon=True,
        )
        thread.start()

    logger.info("All agent sessions aborted due to file load")


@persistent
def _on_load_post(*_args) -> None:
    """Sanitize persisted chat enums after a file loads.

    mixie_chat_mode is saved in the .blend as an int. Files written by
    builds whose enum had items that no longer exist (the old ASK mode
    stored value 2) load with an out-of-range int: bpy then logs
    "current value '2' matches no enum" on EVERY read — i.e. every
    footer/bubble redraw — and reads return "". Reset such scenes to
    'AGENT' once, right after load, so the file is clean from then on.
    """
    import bpy as _bpy

    for scene in _bpy.data.scenes:
        try:
            if not hasattr(scene, "mixie_chat_mode"):
                continue
            # Invalid persisted ints read back as "" (no matching item).
            if scene.mixie_chat_mode not in ('AGENT', 'GENERATE', 'LIBRARY'):
                scene.mixie_chat_mode = 'AGENT'
                logger.info(
                    "Sanitized stale mixie_chat_mode on scene %r (legacy "
                    "enum value from an older build) -> AGENT", scene.name,
                )
        except Exception as e:  # noqa: BLE001 — never break file load
            logger.debug("chat mode sanitize skipped on %r: %s",
                         getattr(scene, "name", "?"), e)


def _sanitize_once():
    """Timer callback: sanitize the file that was open before we registered.

    load_post only covers files opened AFTER registration; the startup
    file (loaded before add-on registration) needs this one-shot pass.
    """
    _on_load_post()
    return None  # don't repeat


def register():
    """Install load handlers (session cleanup + enum sanitize)."""
    if _on_load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_on_load_pre)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if not bpy.app.timers.is_registered(_sanitize_once):
        bpy.app.timers.register(_sanitize_once, first_interval=0.5)
    logger.debug("File load handlers registered")


def unregister():
    """Remove load handlers."""
    from .export_destination import clear_all_destinations

    clear_all_destinations()
    if _on_load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_on_load_pre)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    try:
        if bpy.app.timers.is_registered(_sanitize_once):
            bpy.app.timers.unregister(_sanitize_once)
    except Exception:
        pass
    logger.debug("File load handlers unregistered")

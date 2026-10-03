# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded, scene-specific leases for backend-authenticated MCP tool calls.

Only admission/release/tick touch Blender and run on the main thread. Script
authorization and transport invalidation are pure, lock-protected operations.
Scene state generations stop old cleanup from ending a newer chat turn.
"""

from dataclasses import dataclass
import threading
import time
import uuid

from ..constants import (
    DEFAULT_TIMEOUT_SECONDS, MAX_ACTIVE_OPERATIONS, MAX_TIMEOUT_SECONDS,
    OPERATION_CONTEXT_KEY, RETIRED_OPERATION_SECONDS,
)


@dataclass(frozen=True)
class Operation:
    operation_id: str
    session_id: str
    scene_pointer: int
    scene_name: str
    state_generation: int
    deadline: float


_lock = threading.RLock()
_operations = {}
_retired = {}
_cleanup = []
_state_generations = {}
_transport_generation = 0


#: A connection's scene vanishes when another document is opened (File > New or
#: Open, a reopened project); nothing picks the new one silently.
DOCUMENT_CHANGED = ("Another Mixar document was opened, so this connection's scene is gone. Bind the scene "
                    "now shown with mixar_ui_context(session=<its session_id>), or list tabs with mixar_scenes "
                    "and pick one with mixar_scene_switch, then inspect before editing")


def _runtime():
    import bpy
    from mixar.modules.space_mixie_chat.core.session import get_session_manager
    return bpy, get_session_manager()


def _enabled():
    from mixar.config.config import get_config
    return get_config().get("mcp_enabled") is True


def _pointer(scene):
    return scene.as_pointer() if hasattr(scene, "as_pointer") else id(scene)


def _failure(code, message):
    return {"success": False, "error_type": code, "error": message}


def _uuid(value):
    if not isinstance(value, str):
        raise ValueError("must be a UUID string")
    parsed = uuid.UUID(value)
    if str(parsed) != value.lower():
        raise ValueError("must be a canonical UUID string")
    return str(parsed)


def transport_generation():
    with _lock:
        return _transport_generation


def _retire(operation):
    _operations.pop(operation.session_id, None)
    _retired[operation.operation_id] = time.monotonic() + RETIRED_OPERATION_SECONDS


def _receipt(operation):
    return {"success": True, "operation_id": operation.operation_id,
            "session_id": operation.session_id, "scene_name": operation.scene_name,
            "expires_in_seconds": max(0, int(operation.deadline - time.monotonic()))}


def begin_operation(params):
    """Acquire an idle scene. Repeating an active operation never extends it."""
    if not _enabled():
        return _failure("mcp_disabled", "Enable MCP in Mixar first (profile menu > Connect AI Apps (MCP))")
    try:
        operation_id = _uuid(params.get("operation_id"))
        session_id = _uuid(params["session_id"]) if params.get("session_id") else ""
        timeout = params.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be an integer between 1 and 600")
    except (ValueError, TypeError, AttributeError) as exc:
        return _failure("invalid_params", str(exc))
    tick()
    from mixar.modules.common.ui_control.core.ownership import active as ui_active
    if ui_active():
        return _failure("ui_busy", "Release UI control before starting a scene operation")
    from mixar.modules.common.ui_control.core.observe import invalidate as invalidate_ui
    invalidate_ui()
    bpy, session = _runtime()
    from mixar.modules.space_mixie_chat.constants import SessionState, is_lane_scene
    scenes = list(bpy.data.scenes)
    if session_id:
        matches = [s for s in scenes if session.get_session_id(s) == session_id]
    else:
        current = getattr(bpy.context, "scene", None)
        matches = [current] if current is not None and current in scenes else []
    if session_id and not matches:
        return _failure("document_changed", DOCUMENT_CHANGED)
    if len(matches) != 1 or is_lane_scene(matches[0]):
        return _failure("scene_unavailable", "Choose one existing, unambiguous scene")
    scene = matches[0]
    existing_session = session.get_session_id(scene)
    if existing_session and sum(session.get_session_id(s) == existing_session for s in scenes) != 1:
        return _failure("scene_unavailable", "Scene session identity is duplicated")
    from mixar.modules.space_mixie_chat.core.scene_identity import adopt_scene
    adopt_scene(scene)  # Made by a script moments ago: ready, not OFFLINE.
    scene_pointer = _pointer(scene)
    with _lock:
        if operation_id in _retired:
            return _failure("operation_expired", "This operation has already ended")
        existing = next((o for o in _operations.values() if o.operation_id == operation_id), None)
        if existing:
            if existing.scene_pointer != scene_pointer:
                return _failure("operation_conflict", "Operation belongs to another scene")
            return _receipt(existing)
        if session.get_state(scene) == SessionState.OFFLINE:
            return _failure("scene_offline", "Mixar is not connected to its server; wait for it to reconnect")
        if session.get_state(scene) != SessionState.IDLE or session.run_open(scene):
            return _failure("scene_busy", "Wait for the current Mixar task to finish")
        if session.get_session_id(scene) in _operations:
            return _failure("scene_busy", "Another MCP operation owns this scene")
        if len(_operations) >= MAX_ACTIVE_OPERATIONS:
            return _failure("operation_limit", "Too many active MCP operations")
        if not session.get_session_id(scene):
            scene.mixie_session_id = str(uuid.uuid4())
        session_id = session.get_session_id(scene)
        # Legacy/lane routing aliases must never become MCP scene identities.
        try:
            _uuid(session_id)
        except (ValueError, TypeError, AttributeError):
            return _failure("scene_unavailable", "Scene has an unsupported session identity")
        session.set_state(scene, SessionState.BUSY)
        if hasattr(scene, "mixie_chat_active_turn_mode"):
            scene.mixie_chat_active_turn_mode = "AGENT"
        operation = Operation(operation_id, session_id, scene_pointer, scene.name,
                              _state_generations.get(scene_pointer, 0), time.monotonic() + timeout)
        _operations[session_id] = operation
    return _receipt(operation)


def end_operation(params):
    """Release only the matching owner; a delayed end cannot clear new work."""
    try:
        operation_id, session_id = _uuid(params.get("operation_id")), _uuid(params.get("session_id"))
    except (ValueError, TypeError, AttributeError) as exc:
        return _failure("invalid_params", str(exc))
    with _lock:
        operation = _operations.get(session_id)
        if operation is None:
            return {"success": True, "released": False}
        if operation.operation_id != operation_id:
            return _failure("operation_conflict", "Another operation owns this scene")
        _retire(operation)
    _restore(operation)
    return {"success": True, "released": True}


def authorize_script(session_id, agent_ctx):
    """Thread-safe fence, checked both at ingress and immediately before exec."""
    context = agent_ctx if isinstance(agent_ctx, dict) else {}
    operation_id = context.get(OPERATION_CONTEXT_KEY)
    context_session = context.get("chat_session_id") or session_id
    with _lock:
        operation = _operations.get(session_id) or _operations.get(context_session)
        if operation is None and not operation_id:
            # A legacy active-scene alias cannot enter any leased scene.
            if _operations and (not session_id or str(session_id).startswith("agent:")):
                return _failure("mcp_operation_required", "MCP execution needs explicit scene routing")
            return None
        if (operation is None or operation.operation_id != operation_id
                or operation.deadline <= time.monotonic() or session_id != operation.session_id
                or context_session != operation.session_id):
            return _failure("mcp_operation_expired", "MCP operation is missing, expired or belongs to another scene")
    return None


def any_active_operation():
    """True while any MCP scene operation still holds its lease."""
    with _lock:
        return any(operation.deadline > time.monotonic() for operation in _operations.values())


def has_active_operation(session_id):
    """Read-only signal for the existing viewport lock, scoped to one scene."""
    with _lock:
        operation = _operations.get(session_id)
        return operation is not None and operation.deadline > time.monotonic()


def state_changed(scene, state):
    """Called before a real session-state transition on the main thread."""
    pointer = _pointer(scene)
    with _lock:
        _state_generations[pointer] = _state_generations.get(pointer, 0) + 1
        operation = _operations.get(getattr(scene, "mixie_session_id", ""))
        if operation is not None:
            _retire(operation)


def invalidate():
    """Fence immediately on disconnect, including already scheduled begins.

    No bpy access; main-thread tick performs any owned busy-state restoration.
    """
    global _transport_generation
    with _lock:
        _transport_generation += 1
        for operation in list(_operations.values()):
            _retire(operation)
            _cleanup.append(operation)


def invalidate_transport(client):
    """An old socket finishing teardown cannot revoke its replacement's work."""
    from mixar.modules.space_mixie_chat.core.jsonrpc_client import get_jsonrpc_client
    if get_jsonrpc_client() is client:
        invalidate()


def _restore(operation):
    bpy, session = _runtime()
    from mixar.modules.space_mixie_chat.constants import SessionState
    with _lock:
        if (operation.session_id in _operations
                or _state_generations.get(operation.scene_pointer, 0) != operation.state_generation):
            return
    matches = [s for s in bpy.data.scenes
               if session.get_session_id(s) == operation.session_id and _pointer(s) == operation.scene_pointer]
    if len(matches) == 1 and session.get_state(matches[0]) == SessionState.BUSY and not session.run_open(matches[0]):
        session.set_state(matches[0], SessionState.IDLE)


def tick():
    """Expire abandoned leases without resetting a later normal chat turn."""
    now = time.monotonic()
    with _lock:
        for operation in list(_operations.values()):
            if operation.deadline <= now:
                _retire(operation)
                _cleanup.append(operation)
        cleanup, _cleanup[:] = list(_cleanup), []
        for operation_id, until in list(_retired.items()):
            if until <= now:
                _retired.pop(operation_id, None)
    for operation in cleanup:
        _restore(operation)
    return 1.0


def _on_document_change(*_):
    invalidate()
    tick()


def register():
    """Persistent invalidation on file replacement and undo/redo boundaries."""
    bpy, _ = _runtime()
    for name in ("load_pre", "undo_pre", "redo_pre"):
        handlers = getattr(bpy.app.handlers, name)
        bpy.app.handlers.persistent(_on_document_change)
        if _on_document_change not in handlers:
            handlers.append(_on_document_change)
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=1.0, persistent=True)


def unregister(*, shutdown=False):
    invalidate()
    if shutdown:
        # atexit runs after Blender has freed its datablocks.
        return
    tick()
    bpy, _ = _runtime()
    for name in ("load_pre", "undo_pre", "redo_pre"):
        handlers = getattr(bpy.app.handlers, name)
        if _on_document_change in handlers:
            handlers.remove(_on_document_change)
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)

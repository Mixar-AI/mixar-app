# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The conversation half of a checkpoint jump: backend bookmarks and rewinds.

``checkpoint.mark`` bookmarks a fresh tip or safety record; ``checkpoint.rewind``
forks the session thread to the record the scene landed on. Both go over the
agent socket on a worker thread, in order; ``rewind_in_flight`` is true until
they answer, and the composer refuses to send meanwhile. Notices reach the
chat as agent bubbles on the main thread. See
``docs/api/frontend/turn-checkpoints.md`` in mixar-backend.
"""

import threading

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_rewind_inflight = False
_LOCK = threading.Lock()


def rewind_in_flight() -> bool:
    return _rewind_inflight


def _session_scene(session_id: str):
    import bpy
    for scene in bpy.data.scenes:
        if getattr(scene, "mixie_session_id", "") == session_id:
            return scene
    return bpy.context.window.scene if bpy.context.window else bpy.context.scene


def _send_backend(session_id: str, calls: list) -> None:
    """Run the backend bookmarks/rewind on a worker thread, in order."""
    global _rewind_inflight
    if not calls:
        return
    scene_name = ""
    try:
        scene = _session_scene(session_id)
        scene_name = scene.name if scene else ""
    except Exception:  # noqa: BLE001
        pass
    with _LOCK:
        _rewind_inflight = True

    def _run():
        global _rewind_inflight
        from mixar.modules.common.agent_rpc.client import request
        failure = ""
        try:
            for method, payload in calls:
                reply = request(method, payload, mutation=True)
                logger.info(f"Turn checkpoint {method} -> {reply!r}"[:400])
                if isinstance(reply, dict) and (reply.get("ok") is False or reply.get("status") == "failure"):
                    raise RuntimeError(reply.get("message") or f"{method} refused")
                # The backend only forks when the bookmark has a checkpoint id.
                # `has_conversation: false` means NOTHING was forked, and the
                # contract says the client clears its session id so the next
                # message starts a new one. We were deciding from our own local
                # `session_was_new` instead, which is a different question --
                # so a .blend carrying a session id whose backend thread was
                # purged (or belongs to the other environment) rolled the scene
                # back while the agent kept remembering every reverted turn.
                if (method == "checkpoint.rewind" and isinstance(reply, dict)
                        and reply.get("has_conversation") is False):
                    _clear_session_on_main(scene_name)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Turn checkpoint backend call failed: {e}")
            failure = str(e)
        finally:
            with _LOCK:
                _rewind_inflight = False
        if failure:
            _notify(scene_name, "Scene restored, but the conversation could not be rewound: "
                                f"{failure}. The agent may still remember the undone turns.")

    threading.Thread(target=_run, name="mixie-turn-checkpoint", daemon=True).start()


def _clear_session_on_main(scene_name: str) -> None:
    """Drop the session id from the worker thread (bpy only on the main one)."""
    def _clear():
        try:
            import bpy
            from .session import get_session_manager
            scene = bpy.data.scenes.get(scene_name) if scene_name else None
            scene = scene or (bpy.context.window.scene if bpy.context.window else bpy.context.scene)
            if scene is not None:
                if hasattr(scene, "mixie_checkpoint_session_id"):
                    scene.mixie_checkpoint_session_id = getattr(scene, "mixie_session_id", "") or ""
                get_session_manager().clear_session_id(scene)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not clear the session id after a bookmark-less rewind: {e}")
        return None
    try:
        import bpy as _bpy
        _bpy.app.timers.register(_clear, first_interval=0.0)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Session clear timer skipped: {e}")
    _notify(scene_name, "Scene restored. That checkpoint predates the conversation, "
                        "so the next message starts a new chat.")


def _notify(scene_name: str, text: str) -> None:
    """Add an agent bubble on the main thread (safe from any thread)."""
    def _add():
        try:
            import bpy
            from .message_helpers import add_agent_message
            from .ui_utils import redraw_chat_areas
            scene = bpy.data.scenes.get(scene_name) if scene_name else None
            scene = scene or (bpy.context.window.scene if bpy.context.window else bpy.context.scene)
            add_agent_message(scene, text)
            redraw_chat_areas()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"checkpoint notice skipped: {e}")
        return None
    try:
        import bpy as _bpy
        _bpy.app.timers.register(_add, first_interval=0.05)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"checkpoint notice timer skipped: {e}")

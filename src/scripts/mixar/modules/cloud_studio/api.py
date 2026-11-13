# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The app's supported surface for Mixar Game Studio's bridge.

Everything here calls the app's own operators and services on the main thread, exactly as the UI
does: nothing is reimplemented, and nothing reaches the backend on its own. The bridge that calls
this is shipped by the backend, so this module is the only contract between the two: add to it,
never change what a function returns (bump ``API_VERSION`` in ``__init__`` when you add).

    chat_state(scene)                     {"state", "phase", "run_open", "can_send", "why_not"}
    conversation(scene, limit)            the last bubbles as plain data (shape.message)
    session_id(scene)                     the agent session the scene's chat belongs to
    send(scene, text, images, folder)     say something to the agent, with image files attached
    choose(bubble_id, value)              press one of the choices the agent offered
    stop()                                stop what the agent is doing
    set_context_rule(scene, mark, text)   add or replace the one global rule that starts with mark
    save_scene(path, root)                save the scene file (a .mixar under root only)
    open_scene(path, root)                open one (a .mixar under root only)

Each acting function returns ``(ok, error)``; ``error`` is a short sentence safe to show.
"""

import os

from . import shape

MAX_PROMPT = 6000
MAX_IMAGES = 4
MAX_RULE = 4000


def main_window():
    """The app's main window (the assistant's floating window is one too)."""
    import bpy

    windows = list(bpy.context.window_manager.windows)
    for window in windows:
        if any(area.type == "VIEW_3D" for area in window.screen.areas):
            return window
    return windows[0] if windows else None


def active_scene():
    import bpy

    window = main_window()
    return (window.scene if window else None) or bpy.context.scene or bpy.data.scenes[0]


def _run(operator, **props):
    import bpy

    window = main_window()
    if window is None:
        return False, "Mixar has no window yet"
    with bpy.context.temp_override(window=window, screen=window.screen, scene=window.scene):
        try:
            ready = operator.poll()
        except AttributeError:  # the operator is not registered (yet)
            ready = False
        if not ready:
            return False, "Mixar is not ready for that yet"
        result = operator(**props)
    if "FINISHED" in result:
        return True, ""
    return False, "Mixar did not accept that"


def chat_ready():
    """The chat's operators are registered a moment after the app's window is up."""
    import bpy

    return hasattr(bpy.types, "MIXIE_CHAT_OT_send_message")


def chat_state(scene):
    from mixar.modules.space_mixie_chat.core.composer_send import can_send
    from mixar.modules.space_mixie_chat.core.session import get_session_manager

    manager = get_session_manager()
    state = manager.get_state(scene)
    name = str(getattr(state, "name", "") or getattr(state, "value", state)).lower()
    try:
        run_open = bool(manager.run_open(scene))
    except Exception:
        run_open = False
    allowed, reason = can_send(scene)
    if allowed and not chat_ready():
        allowed, reason = False, "Mixar is still starting"
    return {
        "state": name,
        "phase": shape.phase(name, run_open),
        "run_open": run_open,
        "can_send": bool(allowed),
        "why_not": str(reason or ""),
    }


def conversation(scene, limit=shape.MAX_MESSAGES):
    return shape.messages(scene.mixie_chat_messages, limit)


def session_id(scene):
    return shape.clip(getattr(scene, "mixie_session_id", ""), 128)


def send(scene, text, images=None, folder=None):
    """Send ``text`` as the person's message. ``images`` are attached only when they are files
    directly inside ``folder`` (the bridge's own); anything else is silently left out."""
    import bpy

    from mixar.modules.space_mixie_chat.core.composer_send import can_send

    text = str(text or "").strip()
    if not text:
        return False, "Nothing to send"
    if scene.mixie_chat_mode != "AGENT":
        scene.mixie_chat_mode = "AGENT"
    allowed, reason = can_send(scene)
    if not allowed:
        return False, str(reason or "The agent is not ready")
    for path in list(images or [])[:MAX_IMAGES]:
        path = shape.attachable(path, folder)
        if path is None:
            continue
        try:
            _run(bpy.ops.mixie_chat.add_image_from_file, filepath=path)
        except Exception:  # the image is a help, never a reason to drop the message
            pass
    return _run(bpy.ops.mixie_chat.send_message, message_override=text[:MAX_PROMPT])


def choose(bubble_id, value):
    import bpy

    return _run(bpy.ops.mixie_chat.select_slot_action, bubble_id=str(bubble_id or ""), action_value=str(value or ""))


def stop():
    import bpy

    return _run(bpy.ops.mixie_chat.abort_session)


def set_context_rule(scene, mark, text):
    """Add the rule, or replace the one global rule that already starts with ``mark``."""
    from mixar.modules.space_mixie_chat.core import rules_api

    mark = str(mark or "").strip()
    text = shape.clip(str(text or "").strip(), MAX_RULE)
    if not mark or not text.startswith(mark):
        return False, "Not a project context"
    mine = [r for r in rules_api.list_unified(scene) if str(r.get("text") or "").startswith(mark)]
    if mine:
        result = rules_api.update_rule(scene, rule_id=mine[0].get("id"), text=text)
    else:
        result = rules_api.add_rule(scene, text, rules_api.SCOPE_GLOBAL)
    if not result.get("success"):
        return False, shape.clip(result.get("error") or "The project context could not be set", 200)
    return True, ""


def save_scene(path, root):
    import bpy

    path = shape.scene_file(path, root)
    if path is None:
        return False, "That is not a project file"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if bpy.data.filepath and os.path.realpath(bpy.data.filepath) == path:
        return _run(bpy.ops.wm.save_mainfile)
    return _run(bpy.ops.wm.save_as_mainfile, filepath=path, check_existing=False)


def open_scene(path, root):
    import bpy

    path = shape.scene_file(path, root)
    if path is None or not os.path.isfile(path):
        return False, "That project file is not here"
    return _run(bpy.ops.wm.open_mainfile, filepath=path, load_ui=False)


def scene_file_state():
    import bpy

    return {"path": os.path.basename(bpy.data.filepath or ""), "dirty": bool(bpy.data.is_dirty)}

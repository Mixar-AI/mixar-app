# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene tabs: one Blender Scene + one chat session each (parallel scenes).

- ``mixie_chat.new_scene_tab``: an EMPTY scene (never a copy: a copy would
  carry the chat session tag and the transcript) that joins the live
  connection, becomes the scene every window shows, and gets its own session
  on its first message.
- ``mixie_chat.switch_scene_tab``: show a tab. Every window of the app
  follows: the island and pill are companion windows with their own
  ``scene`` pointer, so switching only the main window would leave the chat
  on the previous tab.
- ``mixie_chat.close_scene_tab``: stop, then close. A running tab is aborted
  exactly like the Abort button (its turn torn down, its queued scripts
  dropped, the backend run cancelled) BEFORE the scene goes: the per-session
  active gate then refuses any script that still arrives for it. The chat is
  archived to History, the window moves to a neighbour, the tab's worker lanes
  are swept, and the scene is removed. The last real scene never closes.

Design: docs/agent/parallel-scene-tabs/ (mixar-backend).
"""

from __future__ import annotations

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.scenes_log import slog

from ...constants import SessionState, is_lane_scene
from ...core import get_connection_manager, get_session_manager
from ...core.scene_tab_send import send_selection_to_scene  # noqa: F401 — the send operator's worker

logger = get_logger(__name__)

PENDING_CLOSE_PROP = "mixie_pending_close"
#: Custom property holding a tab's position in the drawer (saved with the file).
ORDER_PROP = "mixar_tab_order"


def tab_order(scene) -> int:
    try:
        return int(scene.get(ORDER_PROP, 1_000_000))
    except Exception:  # noqa: BLE001
        return 1_000_000


def ordered_tabs() -> list:
    """The user's tabs in drawer order: explicit order first, then name."""
    return sorted(real_scenes(), key=lambda s: (tab_order(s), s.name))


def renumber_tabs(tabs=None) -> None:
    for index, scene in enumerate(tabs if tabs is not None else ordered_tabs()):
        try:
            scene[ORDER_PROP] = index
        except Exception:  # noqa: BLE001
            pass


def reorder_scene_tab(scene, index: int) -> bool:
    """Move ``scene`` to position ``index`` among the tabs. False for a lane."""
    if scene is None or is_lane_scene(scene):
        return False
    tabs = ordered_tabs()
    if scene not in tabs:
        return False
    tabs.remove(scene)
    tabs.insert(max(0, min(int(index), len(tabs))), scene)
    renumber_tabs(tabs)
    slog("tab.reorder", scene, index=index, order=[s.name for s in tabs])
    return True


def real_scenes() -> list:
    """The user's tabs: every scene that is not an agent worker lane."""
    return [s for s in bpy.data.scenes if not is_lane_scene(s)]


def switch_all_windows(scene, showing=None) -> None:
    """Show ``scene`` in every window (main and companions) — or, with
    ``showing``, only in the windows that currently show that scene."""
    for wm in bpy.data.window_managers:
        for window in wm.windows:
            try:
                if showing is not None and window.scene is not showing:
                    continue
                if window.scene is not scene:
                    window.scene = scene
            except Exception:  # noqa: BLE001 — a companion mid-teardown
                logger.debug("window could not switch scene", exc_info=True)


def _connection_live() -> bool:
    try:
        connected = get_connection_manager().is_connected
        return bool(connected() if callable(connected) else connected)
    except Exception:  # noqa: BLE001
        return False


def _running(scene) -> bool:
    session = get_session_manager()
    return (session.get_state(scene) in (SessionState.BUSY, SessionState.MODIFYING,
                                          SessionState.AWAITING_INPUT)
            or session.run_open(scene))


def _unique_name(base: str) -> str:
    name, n = base, 2
    while name in bpy.data.scenes:
        name = f"{base} {n}"
        n += 1
    return name


#: Login identity the auth flow stamps on the scene it signed in from; a new
#: tab inherits it, or the profile chip and credits read blank there.
ACCOUNT_PROPS = ("mixie_chat_user_id", "mixie_chat_credits", "mixie_chat_model")


def inherit_account(source, scene) -> None:
    """Copy the signed-in identity from ``source`` onto a new tab's scene."""
    if source is None or source is scene:
        return
    for prop in ACCOUNT_PROPS:
        try:
            setattr(scene, prop, getattr(source, prop))
        except Exception:  # noqa: BLE001 — a missing property on either side is fine
            pass


#: Blender's startup file placement for the camera and the key light, so a
#: new tab starts like a new file does (minus the cube).
_DEFAULT_CAMERA = ((7.3589, -6.9258, 4.9583), (1.1093, 0.0, 0.8149))
_DEFAULT_LIGHT = ((4.0762, 1.0055, 5.9039), (0.6503, 0.0553, 1.8664), 1000.0)


def inherit_settings(source, scene) -> None:
    """Render, colour, unit and frame settings of the source tab, and its OWN
    copy of the world: tabs never share datablocks, so a world tweak in one
    tab cannot reach another."""
    if source is None or source is scene:
        return
    try:
        scene.render.engine = source.render.engine
        scene.render.resolution_x = source.render.resolution_x
        scene.render.resolution_y = source.render.resolution_y
        scene.render.resolution_percentage = source.render.resolution_percentage
        scene.render.fps = source.render.fps
        scene.frame_start, scene.frame_end = source.frame_start, source.frame_end
        scene.unit_settings.system = source.unit_settings.system
        scene.unit_settings.scale_length = source.unit_settings.scale_length
        scene.view_settings.view_transform = source.view_settings.view_transform
        scene.view_settings.look = source.view_settings.look
    except Exception as error:  # noqa: BLE001
        logger.debug("new tab settings partly inherited: %s", error)
    try:
        world = getattr(source, "world", None)
        scene.world = world.copy() if world is not None else None
    except Exception as error:  # noqa: BLE001
        logger.debug("new tab world not copied: %s", error)


def furnish_scene(scene) -> list:
    """A camera and a light where a new Blender file puts them; the camera
    becomes the scene camera. Returns the objects made."""
    made = []
    try:
        cam_data = bpy.data.cameras.new("Camera")
        camera = bpy.data.objects.new("Camera", cam_data)
        camera.location, camera.rotation_euler = _DEFAULT_CAMERA
        scene.collection.objects.link(camera)
        scene.camera = camera
        made.append(camera)
        light_data = bpy.data.lights.new("Light", 'POINT')
        light_data.energy = _DEFAULT_LIGHT[2]
        light = bpy.data.objects.new("Light", light_data)
        light.location, light.rotation_euler = _DEFAULT_LIGHT[0], _DEFAULT_LIGHT[1]
        scene.collection.objects.link(light)
        made.append(light)
    except Exception as error:  # noqa: BLE001
        logger.warning("new tab could not be furnished: %s", error)
    return made


def new_scene_tab(name: str = "") -> object:
    """Create a tab that starts like a new file (camera, light, the source
    tab's settings), connect it, show it everywhere. Returns the scene."""
    existing = ordered_tabs()
    source = getattr(getattr(bpy.context, "window", None), "scene", None) or (existing[0] if existing else None)
    scene = bpy.data.scenes.new(_unique_name((name or "").strip() or "Scene"))
    # A fresh tab: no session yet (minted on the first message), no chat, but
    # the same signed-in account and settings as the tab it was opened from.
    scene.mixie_session_id = ""
    inherit_account(source, scene)
    inherit_settings(source, scene)
    furnish_scene(scene)
    session = get_session_manager()
    live = _connection_live()
    if live:
        session.set_connected(scene)          # IDLE: the composer accepts a message
    else:
        session.set_disconnected(scene)
    switch_all_windows(scene)
    renumber_tabs(existing + [scene])      # the new tab takes the last slot
    slog("tab.new", scene, connected=live, tabs=len(real_scenes()))
    return scene


def switch_scene_tab(scene, was=None) -> bool:
    """Show a tab in every window. False for a lane or a missing scene."""
    if scene is None or is_lane_scene(scene):
        return False
    switch_all_windows(scene)
    slog("tab.switch", scene, was=getattr(was, "name", ""))
    return True


def stop_scene_tab(scene, sid: str) -> None:
    """Abort this tab's turn and run, exactly like the Abort button, and tell
    the backend. Other tabs are untouched: every step is keyed by this scene
    or its session."""
    from ...core.executor import get_executor
    from ...core.main_thread_executor import cleanup as flush_executor_queue
    from ...core.queue_processor import cleanup_event_queue_for_scene
    from ...core.turn_transport import cleanup_turn_handler
    from .session_ops import send_cancel_request_async

    session = get_session_manager()
    cleanup_turn_handler(scene.name)
    cleanup_event_queue_for_scene(scene.name)
    flush_executor_queue(session_id=sid)
    get_executor().end_agent_turn(sid)
    session.set_run(scene, "", False)
    session.set_state(scene, SessionState.IDLE)
    if sid:
        send_cancel_request_async(sid)
    slog("tab.close.cancel", scene)


def close_scene_tab(scene, report=None) -> tuple[bool, str]:
    """Stop, then close. Returns ``(closed, reason)``."""
    if scene is None or is_lane_scene(scene):
        return False, "That scene is not a tab"
    tabs = real_scenes()
    if len(tabs) <= 1:
        return False, "Keep at least one scene open"
    session = get_session_manager()
    sid = session.get_session_id(scene) or ""
    slog("tab.close.prompt", scene, running=_running(scene))

    if _running(scene):
        if not _connection_live():
            # The backend cannot be told to stop; closing now would leave its
            # run building into a scene that no longer exists.
            slog("tab.close.refused", scene, reason="offline")
            return False, "Reconnect to stop the agent before closing this scene"
        stop_scene_tab(scene, sid)

    # Archive the chat (recoverable from History).
    try:
        from ...core.chat_history import archive_current
        archive_current(scene)
        slog("tab.close.archived", scene)
    except Exception:  # noqa: BLE001 — never block the close
        logger.warning("Could not archive the chat before closing the scene", exc_info=True)

    # Move the windows showing the scene off it first: Blender refuses to
    # remove a window's current scene. A window on another tab stays there —
    # closing a background tab never changes what the user is looking at.
    neighbour = next((s for s in tabs if s is not scene), None)
    switch_all_windows(neighbour, showing=scene)
    slog("tab.switch", neighbour, was=scene.name, reason="close")

    # The tab's cards and worker lanes go with it, then the scene.
    try:
        from mixar.modules.agent_panel.core.cards import clear_cards
        clear_cards(scene=scene)
    except Exception:  # noqa: BLE001
        pass
    if sid:
        try:
            from ...core.lane_scene_sweep import sweep_leaked_lane_scenes
            sweep_leaked_lane_scenes(parent_session_id=sid)
        except Exception:  # noqa: BLE001
            logger.warning("Lane sweep on close failed", exc_info=True)
    name = scene.name
    try:
        bpy.data.scenes.remove(scene)
    except Exception as exc:  # noqa: BLE001
        slog("tab.close.failed", None, session_id=sid, scene_name=name, error=str(exc)[:120])
        return False, "Could not remove the scene"
    slog("tab.close.deleted", None, session_id=sid, scene_name=name, tabs=len(real_scenes()))
    return True, ""


class MIXIE_CHAT_OT_new_scene_tab(Operator):
    """Open a new scene with its own agent chat"""

    bl_idname = "mixie_chat.new_scene_tab"
    bl_label = "New Scene"
    bl_description = "Open a new, empty scene with its own agent chat"
    bl_options = {'REGISTER'}

    name: StringProperty(name="Name", default="", options={'SKIP_SAVE'})

    def execute(self, context):
        new_scene_tab(self.name)
        return {'FINISHED'}


class MIXIE_CHAT_OT_switch_scene_tab(Operator):
    """Show a scene tab"""

    bl_idname = "mixie_chat.switch_scene_tab"
    bl_label = "Switch Scene"
    bl_description = "Show this scene and its chat"
    bl_options = {'REGISTER', 'INTERNAL'}

    scene_name: StringProperty(name="Scene", default="", options={'SKIP_SAVE'})

    def execute(self, context):
        was = getattr(getattr(context, "window", None), "scene", None)
        if not switch_scene_tab(bpy.data.scenes.get(self.scene_name), was):
            self.report({'WARNING'}, "That scene is not a tab")
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXIE_CHAT_OT_reorder_scene_tab(Operator):
    """Move a scene tab to a position in the drawer"""

    bl_idname = "mixie_chat.reorder_scene_tab"
    bl_label = "Reorder Scene"
    bl_options = {'REGISTER', 'INTERNAL'}

    scene_name: StringProperty(name="Scene", default="", options={'SKIP_SAVE'})
    index: IntProperty(name="Index", default=0, min=0, options={'SKIP_SAVE'})

    def execute(self, context):
        if not reorder_scene_tab(bpy.data.scenes.get(self.scene_name), self.index):
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXIE_CHAT_OT_send_to_scene_tab(Operator):
    """Copy the selected objects into another scene tab (duplicates, never
    links: the tabs stay independent)."""

    bl_idname = "mixie_chat.send_to_scene_tab"
    bl_label = "Send Selection to Scene"
    bl_description = "Copy the selected objects (with their mesh and materials) into another tab"
    bl_options = {'REGISTER', 'UNDO'}

    scene_name: StringProperty(name="Scene", default="", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return bool(getattr(context, "selected_objects", None))

    def execute(self, context):
        target = bpy.data.scenes.get(self.scene_name)
        if target is None or target is context.scene:
            self.report({'WARNING'}, "Pick another scene tab")
            return {'CANCELLED'}
        made = send_selection_to_scene(context.scene, target, list(context.selected_objects))
        if not made:
            self.report({'WARNING'}, "Nothing was copied")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Copied {len(made)} object(s) to {target.name}")
        return {'FINISHED'}


class MIXIE_CHAT_OT_show_scene_tabs(Operator):
    """Pop the scene-tab menu from the island header: this chat's tab,
    every other tab with its agent status, and New scene."""

    bl_idname = "mixie_chat.show_scene_tabs"
    bl_label = "Scene tabs"
    bl_description = "This chat's scene tab; jump to another tab or open a new one"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return bpy.ops.wm.call_menu(name="MIXIE_CHAT_MT_scene_tabs")

    def execute(self, context):
        return bpy.ops.wm.call_menu(name="MIXIE_CHAT_MT_scene_tabs")


class MIXIE_CHAT_OT_close_scene_tab(Operator):
    """Close a scene tab (stops its agent first)"""

    bl_idname = "mixie_chat.close_scene_tab"
    bl_label = "Close Scene"
    bl_description = "Stop this scene's agent, save its chat to History and remove the scene"
    bl_options = {'REGISTER'}

    scene_name: StringProperty(name="Scene", default="", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return len(real_scenes()) > 1

    def execute(self, context):
        scene = bpy.data.scenes.get(self.scene_name) if self.scene_name else context.scene
        closed, reason = close_scene_tab(scene)
        if not closed:
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_new_scene_tab,
    MIXIE_CHAT_OT_switch_scene_tab,
    MIXIE_CHAT_OT_reorder_scene_tab,
    MIXIE_CHAT_OT_close_scene_tab,
    MIXIE_CHAT_OT_show_scene_tabs,
    MIXIE_CHAT_OT_send_to_scene_tab,
)

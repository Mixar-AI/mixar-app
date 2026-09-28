# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene tabs: the drawer's state and the tab list the C++ drawer paints.

WindowManager properties shared with ``editors/space_view3d/view3d_scenes_drawer*``:

  - ``mixar_scenes_drawer_amount`` / ``_target`` / ``_width`` / ``_width_ready``:
    the same slide state the moodboard drawer keeps (see
    ``modules/moodboard/ui/moodboard_drawer_props.py``); this module's clock
    calls ``view3d.scenes_drawer_update`` so RNA meets the target.
  - ``mixar_scene_tabs``: one row per user scene (never a worker lane), refreshed
    here from the scenes' chat state, the agent cards mirror and the last agent
    message. C reads it on every draw and never writes it.
  - ``mixar_scene_tabs_attention``: True while any background tab needs the user
    (a parked question, or a run that finished since the tab was last shown);
    the toolbar button shows a dot for it.

All properties are SKIP_SAVE: a slide in progress and a projection of live
state are never scene data.
"""

import time

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, StringProperty)
from bpy.types import PropertyGroup

from mixar.config.logging_config import get_logger

from ...core.scene_tab_snapshot import zen_view3d_override

logger = get_logger(__name__)

_ANIMATION_INTERVAL = 1.0 / 60.0
_IDLE_INTERVAL = 0.1
_TABS_INTERVAL = 0.5

STATUS_ITEMS = (
    ('IDLE', "Idle", "", 0),
    ('WORKING', "Working", "", 1),
    ('WAITING', "Waiting for you", "", 2),
    ('DONE', "Done", "", 3),
)

#: session id -> True once its run finished while another tab was on screen;
#: cleared when the tab is shown.
_finished_unseen: dict = {}
_last_status: dict = {}
#: Signature of the last list written, so a redraw is only asked for on change.
_last_signature: tuple = ()


def _tag_zen_viewports() -> None:
    """Repaint the drawer: its region listens for scene/window notifiers, but a
    timer-driven list change sends none."""
    wm = getattr(bpy.context, 'window_manager', None)
    for window in (getattr(wm, 'windows', None) or ()):
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class MixarSceneTab(PropertyGroup):
    scene_uid: StringProperty(options={'SKIP_SAVE'})
    scene_name: StringProperty(name="Scene", default="", options={'SKIP_SAVE'})
    session_id: StringProperty(name="Session", default="", options={'SKIP_SAVE'})
    status: EnumProperty(name="Status", items=STATUS_ITEMS, default='IDLE', options={'SKIP_SAVE'})
    workers_done: IntProperty(name="Workers done", default=0, min=0, options={'SKIP_SAVE'})
    workers_total: IntProperty(name="Workers", default=0, min=0, options={'SKIP_SAVE'})
    is_active: BoolProperty(name="Active", default=False, options={'SKIP_SAVE'})
    attention: BoolProperty(name="Needs attention", default=False, options={'SKIP_SAVE'})
    # The drawer's close glyph deletes an `empty` tab at once (Undo toast) and
    # flips any other card into its in-place confirmation, whose consequence
    # line reads `has_chat` (core/scene_tab_edit.py).
    empty: BoolProperty(name="Nothing to lose", default=False, options={'SKIP_SAVE'})
    has_chat: BoolProperty(name="Has chat", default=False, options={'SKIP_SAVE'})


# --- slide clock (mirror of the moodboard drawer) ---------------------------

_view3d_override = zen_view3d_override


_THUMBS_INTERVAL = 1.0
_last_thumbs = 0.0


def _refresh_thumbs(amount: float) -> None:
    """Refresh the SHOWN tab's card from the viewport's last frame (the operator
    throttles and skips an unchanged scene). Cards are snapshots, never renders:
    a background tab keeps its last picture until it is shown again
    (``core/scene_tab_snapshot.py``)."""
    global _last_thumbs
    now = time.monotonic()
    if amount < 0.98 or now - _last_thumbs < _THUMBS_INTERVAL:
        return
    _last_thumbs = now
    override = _view3d_override()
    if override is None:
        return
    try:
        with bpy.context.temp_override(**override):
            bpy.ops.view3d.scenes_drawer_thumbs()
    except Exception as error:  # noqa: BLE001
        logger.debug("Scenes drawer thumbnails unavailable: %s", error)


def _drawer_tick():
    window_manager = getattr(bpy.context, 'window_manager', None)
    if window_manager is None:
        return _IDLE_INTERVAL
    amount = float(window_manager.mixar_scenes_drawer_amount)
    target = float(window_manager.mixar_scenes_drawer_target)
    _refresh_thumbs(amount)
    if amount == target:
        return _IDLE_INTERVAL
    override = _view3d_override()
    if override is None:
        window_manager.mixar_scenes_drawer_amount = float(target)
        return _IDLE_INTERVAL
    try:
        with bpy.context.temp_override(**override):
            bpy.ops.view3d.scenes_drawer_update()
    except Exception as error:  # noqa: BLE001
        logger.debug("Scenes drawer update unavailable: %s", error)
        window_manager.mixar_scenes_drawer_amount = float(target)
        return _IDLE_INTERVAL
    return _ANIMATION_INTERVAL


# --- the tab list -----------------------------------------------------------

def _status_of(scene) -> str:
    from ...constants import SessionState
    from ...core.session import get_session_manager
    session = get_session_manager()
    state = session.get_state(scene)
    if state in (SessionState.AWAITING_INPUT, SessionState.MODIFYING):
        return 'WAITING'
    if state == SessionState.BUSY or session.run_open(scene):
        return 'WORKING'
    return 'IDLE'


def _workers(session_id: str):
    try:
        from mixar.modules.agent_panel.core.cards import _sessions
        records = _sessions.get(session_id) or []
        done = sum(1 for r in records if r.get("status") in ('DONE', 'FAILED'))
        return done, len(records)
    except Exception:  # noqa: BLE001
        return 0, 0


def _shown_scene():
    window = getattr(bpy.context, "window", None)
    scene = getattr(window, "scene", None) if window is not None else None
    return scene if scene is not None else getattr(bpy.context, "scene", None)


def refresh_scene_tabs() -> int:
    """Rebuild ``wm.mixar_scene_tabs`` from the live scenes. Main thread."""
    wm = getattr(bpy.context, 'window_manager', None)
    if wm is None or not hasattr(wm, "mixar_scene_tabs"):
        return 0
    shown = _shown_scene()
    tabs = wm.mixar_scene_tabs
    records = []
    attention_any = False
    from ..operators.scene_tab_ops import ordered_tabs
    from ...core.scene_tab_edit import tab_has_chat, tab_is_empty
    for scene in ordered_tabs():
        sid = getattr(scene, "mixie_session_id", "") or ""
        status = _status_of(scene)
        is_active = scene is shown
        # A run that finished while this tab was in the background needs a look.
        if sid:
            previous = _last_status.get(sid)
            if previous == 'WORKING' and status != 'WORKING' and not is_active:
                _finished_unseen[sid] = True
            _last_status[sid] = status
            if is_active:
                _finished_unseen.pop(sid, None)
        attention = (not is_active) and (status == 'WAITING' or bool(_finished_unseen.get(sid)))
        attention_any = attention_any or attention
        done, total = _workers(sid)
        records.append((str(scene.session_uid), scene.name, sid,
                        status if status != 'IDLE' or not _finished_unseen.get(sid) else 'DONE',
                        done, total, is_active, attention,
                        tab_is_empty(scene), tab_has_chat(scene)))
    if wm.mixar_scene_tabs_attention != attention_any:
        wm.mixar_scene_tabs_attention = attention_any
    global _last_signature
    signature = tuple(records)
    if signature != _last_signature or len(tabs) != len(records):
        fields = ('scene_uid', 'scene_name', 'session_id', 'status',
                  'workers_done', 'workers_total', 'is_active', 'attention',
                  'empty', 'has_chat')
        tabs.clear()
        for values in records:
            tab = tabs.add()
            for field, value in zip(fields, values):
                setattr(tab, field, value)
        _last_signature = signature
        _tag_zen_viewports()
    return len(tabs)


def _tabs_tick():
    try:
        refresh_scene_tabs()
    except Exception as error:  # noqa: BLE001
        logger.debug("scene tabs refresh skipped: %s", error)
    return _TABS_INTERVAL


# --- registration -----------------------------------------------------------

classes = (MixarSceneTab,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    WM = bpy.types.WindowManager
    WM.mixar_scenes_drawer_amount = FloatProperty(
        name="Scenes Drawer", description="0 shut .. 1 open", default=0.0, min=0.0, max=1.0,
        options={'SKIP_SAVE'})
    WM.mixar_scenes_drawer_target = IntProperty(
        name="Scenes Drawer Target", description="0 shut, 1 open", default=0, min=0, max=1,
        options={'SKIP_SAVE'})
    WM.mixar_scenes_drawer_width = FloatProperty(
        name="Scenes Drawer Width", description="Width chosen by dragging the grip (UI units)",
        default=300.0, min=160.0, max=100000.0, options={'SKIP_SAVE'})
    WM.mixar_scenes_drawer_width_ready = BoolProperty(
        name="Scenes Drawer Width Ready", default=False, options={'SKIP_SAVE'})
    WM.mixar_scene_tabs = CollectionProperty(type=MixarSceneTab, options={'SKIP_SAVE'})
    WM.mixar_scene_tabs_attention = BoolProperty(
        name="Scene tabs need attention", default=False, options={'SKIP_SAVE'})
    if not bpy.app.timers.is_registered(_drawer_tick):
        bpy.app.timers.register(_drawer_tick, first_interval=_IDLE_INTERVAL, persistent=True)
    if not bpy.app.timers.is_registered(_tabs_tick):
        bpy.app.timers.register(_tabs_tick, first_interval=_TABS_INTERVAL, persistent=True)


def unregister():
    for fn in (_drawer_tick, _tabs_tick):
        try:
            if bpy.app.timers.is_registered(fn):
                bpy.app.timers.unregister(fn)
        except Exception:  # noqa: BLE001
            pass
    WM = bpy.types.WindowManager
    for name in ("mixar_scenes_drawer_amount", "mixar_scenes_drawer_target",
                 "mixar_scenes_drawer_width", "mixar_scenes_drawer_width_ready",
                 "mixar_scene_tabs", "mixar_scene_tabs_attention"):
        if hasattr(WM, name):
            try:
                delattr(WM, name)
            except Exception:  # noqa: BLE001
                pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:  # noqa: BLE001
            pass

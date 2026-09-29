# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fresh-scene Cycles defaults on every desktop platform.

File loads snapshot existing scenes before any deferred work: switching engines
later must not silently change a saved project's device or render border.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.modules.common.render_coordinator import core as render_slot
from mixar.modules.space_mixie_chat.core import render_device

_OWNER = object()
_INITIALIZED = "_mixar_cycles_defaults_applied"
_saved_scenes = set()
_ready = False


def apply_scene_defaults(scene, *, startup=False):
    """Initialize fresh scenes once, without overwriting an explicit device."""
    if (not _ready or bpy.app.background or render_slot.busy()
            or scene.session_uid in _saved_scenes or scene.library
            or scene.get(_INITIALIZED)):
        return
    if not startup and scene.render.engine != "CYCLES":
        return
    # RNA stores Cycles' device only when assigned. This also preserves a
    # custom startup file's explicit CPU choice and changes made before Cycles.
    if not scene.cycles.is_property_set("device") and render_device.use_gpu():
        scene.cycles.device = "GPU"
    if scene.render.engine == "CYCLES":
        scene.render.use_border = True
        scene[_INITIALIZED] = True


def _engine_changed():
    # A type-wide notification does not identify the changed scene; context
    # may belong to another window. Visit eligible scenes, never context.scene.
    for scene in bpy.data.scenes:
        apply_scene_defaults(scene)


def apply_startup_defaults():
    """Called after device discovery and the paint preferences' load handlers."""
    global _ready
    if bpy.app.background or render_slot.busy():
        return
    _ready = True
    if not bpy.data.filepath:
        for scene in bpy.data.scenes:
            # Set the device even in an EEVEE startup file, ready for Cycles.
            apply_scene_defaults(scene, startup=True)
    else:
        # A new scene may have been created while the file-load timer waited.
        _engine_changed()


def _subscribe():
    bpy.msgbus.clear_by_owner(_OWNER)
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.RenderSettings, "engine"),
        owner=_OWNER, args=(), notify=_engine_changed,
    )


def _prepare_file():
    global _ready
    _ready = False
    _saved_scenes.clear()
    try:
        filepath = bpy.data.filepath
    except AttributeError:
        # Startup registration sees `_RestrictData`; no file is loaded yet and
        # the load_post that follows snapshots whatever file Blender opens.
        filepath = ""
    if filepath:
        _saved_scenes.update(scene.session_uid for scene in bpy.data.scenes)
    _subscribe()


@persistent
def _on_load(_unused):
    _prepare_file()
    # Timers are cleared by file loading. Defer until ALL load_post handlers
    # have restored preferences, and restart a startup pass cancelled by load.
    from . import render_device_module
    render_device_module.schedule()


def register():
    if bpy.app.background:
        return
    _prepare_file()
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    global _ready
    _ready = False
    _saved_scenes.clear()
    bpy.msgbus.clear_by_owner(_OWNER)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)

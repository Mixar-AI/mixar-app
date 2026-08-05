# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent shot metadata and lightweight directing-session state."""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from ...constants import (
    DEFAULT_BEAT_SECONDS,
    GUIDANCE_STRENGTH_ITEMS,
    MAX_BEAT_SECONDS,
    MIN_BEAT_SECONDS,
    SHOT_STATE_ITEMS,
)


def _camera_poll(_self, obj):
    return getattr(obj, "type", None) == 'CAMERA'


def _activate_shot_camera(self, _context):
    scene = getattr(self, "scene_ref", None)
    camera = getattr(self, "camera", None)
    if scene is not None and camera is not None and camera.type == 'CAMERA':
        scene.camera = camera


def _redraw_director_surface(_self, context):
    """Refresh native Director overlays and poll-driven regions."""
    window_manager = getattr(context, "window_manager", None)
    if window_manager is None:
        window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()):
            if area.type in {'VIEW_3D', 'MIXIE'}:
                area.tag_redraw()


class MixarDirectorBeat(PropertyGroup):
    """One sparse camera pose and its captured moodboard still."""

    beat_id: StringProperty(name="Beat ID", default="")
    frame: IntProperty(name="Frame", default=1, min=-1048574, max=1048574)
    image: PointerProperty(
        name="Reference Frame",
        description="Packed viewport capture associated with this camera beat",
        type=bpy.types.Image,
    )


class MixarDirectorShot(PropertyGroup):
    """A take on a native Blender scene and camera."""

    shot_id: StringProperty(name="Shot ID", default="")
    name: StringProperty(name="Shot", default="Shot 01", maxlen=128)
    version: IntProperty(name="Take", default=1, min=1)
    parent_shot_id: StringProperty(name="Parent Shot ID", default="")
    state: EnumProperty(name="State", items=SHOT_STATE_ITEMS, default="DRAFT")
    scene_ref: PointerProperty(
        name="Scene",
        description="Live scene used as the set for this take",
        type=bpy.types.Scene,
    )
    camera: PointerProperty(
        name="Camera",
        description="Native Blender camera directed by this take",
        type=bpy.types.Object,
        poll=_camera_poll,
        update=_activate_shot_camera,
    )
    prompt: StringProperty(
        name="Direction",
        description="Describe the action and motion to generate between beats",
        default="",
        maxlen=4096,
        options={'TEXTEDIT_UPDATE'},
    )
    guidance_strength: EnumProperty(
        name="Adherence",
        description="How closely the generated video should follow the beats",
        items=GUIDANCE_STRENGTH_ITEMS,
        default="BALANCED",
    )
    beats: CollectionProperty(type=MixarDirectorBeat, name="Camera Beats")
    active_beat_index: IntProperty(name="Active Beat", default=0, min=0)
    manifest_json: StringProperty(
        name="Camera Direction Manifest",
        default="",
        maxlen=65536,
    )
    snapshot_json: StringProperty(
        name="Locked Snapshot",
        default="",
        maxlen=65536,
    )
    locked_at: StringProperty(name="Locked At", default="", maxlen=64)
    manifest_text_name: StringProperty(
        name="Manifest Text",
        default="",
        maxlen=128,
    )


class MixarDirectorState(PropertyGroup):
    """Per-scene shot collection plus non-persistent session controls."""

    shots: CollectionProperty(type=MixarDirectorShot, name="Shots")
    active_shot_index: IntProperty(name="Active Shot", default=0, min=0)
    beat_seconds: FloatProperty(
        name="Beat Spacing",
        description="Time automatically placed between captured camera beats",
        default=DEFAULT_BEAT_SECONDS,
        min=MIN_BEAT_SECONDS,
        max=MAX_BEAT_SECONDS,
        step=10,
        precision=1,
        subtype='TIME',
    )
    is_directing: BoolProperty(
        name="Directing",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
        update=_redraw_director_surface,
    )
    timeline_expanded: BoolProperty(
        name="Timeline",
        description="Show the native shot timeline below the Director viewport",
        default=True,
        options={'SKIP_SAVE'},
        update=_redraw_director_surface,
    )
    is_immersive: BoolProperty(
        name="Immersive View",
        description="Whether Director currently owns a maximized viewport area",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
        update=_redraw_director_surface,
    )
    navigation_mode: EnumProperty(
        name="Camera Control",
        items=(
            ("NAVIGATE", "Navigate", "Move with WASD and the mouse", 0),
            ("PRECISE", "Precise", "Adjust the camera with transform gizmos", 1),
        ),
        default="NAVIGATE",
        options={'SKIP_SAVE'},
    )
    show_shots: BoolProperty(name="Show Shots", default=False)


classes = (
    MixarDirectorBeat,
    MixarDirectorShot,
    MixarDirectorState,
)


def register():
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    bpy.types.Scene.mixar_director = PointerProperty(
        type=MixarDirectorState,
        name="Mixar Director",
        description="Sparse camera-direction shots for this scene",
    )


def unregister():
    if hasattr(bpy.types.Scene, "mixar_director"):
        del bpy.types.Scene.mixar_director
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass

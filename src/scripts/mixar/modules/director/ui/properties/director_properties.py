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
    CAMERA_TEMPLATE_ITEMS,
    DEFAULT_BEAT_SECONDS,
    GUIDANCE_STRENGTH_ITEMS,
    MAX_BEAT_SECONDS,
    MIN_BEAT_SECONDS,
    SHOT_RENDER_OUTPUT_ITEMS,
    SHOT_STATE_ITEMS,
)
from ...core.shot_api import scope_preview_range
from ...core.viewport import enter_camera_view, select_camera_object


def _camera_poll(_self, obj):
    return getattr(obj, "type", None) == 'CAMERA'


def _request_beat_reconcile() -> None:
    """Adopt/prune native camera keys for the newly watched shot right away.

    The beat_sync watcher only ticks on depsgraph updates, which entering
    Director or switching shots does not cause — without this, a camera
    keyed through the native timeline shows an empty Director strip until
    some unrelated edit happens to tick the handler.
    """
    from ...core import beat_sync

    try:
        beat_sync.request_reconcile()
    except Exception:
        # Never let a reconcile request break the camera-switch update.
        pass


def _activate_shot_camera(self, context):
    scene = getattr(self, "scene_ref", None)
    camera = getattr(self, "camera", None)
    if scene is not None and camera is not None and camera.type == 'CAMERA':
        scene.camera = camera
        state = getattr(scene, "mixar_director", None)
        if state is not None and state.is_directing:
            select_camera_object(context or bpy.context, camera)
            try:
                enter_camera_view(context or bpy.context, camera, remember=False)
            except Exception:
                # RNA updates can run without a usable area during file loading.
                pass
        _request_beat_reconcile()


def _on_active_shot_change(self, context):
    """Follow the newly active shot: its camera, view, selection, and range.

    All shots share one scene timeline, so switching shots must re-point the
    scene camera and the playback range or the timeline shows one shot's beats
    while the view and playhead still belong to another. The selection follows
    while directing so gizmos and transform keys edit the new shot's camera.
    """
    scene = getattr(context, "scene", None) or bpy.context.scene
    shots = getattr(self, "shots", None)
    if scene is None or not shots:
        return
    index = min(max(0, self.active_shot_index), len(shots) - 1)
    shot = shots[index]
    camera = getattr(shot, "camera", None)
    if camera is not None and getattr(camera, "type", None) == 'CAMERA':
        scene.camera = camera
        if self.is_directing:
            select_camera_object(context or bpy.context, camera)
            try:
                enter_camera_view(context or bpy.context, camera, remember=False)
            except Exception:
                pass
    scope_preview_range(scene, shot)
    _request_beat_reconcile()


def _on_handheld_update(self, _context):
    from ...core.handheld import refresh_handheld

    try:
        refresh_handheld(self)
    except Exception:
        # Property updates can fire during file load before the camera's
        # animation data is reachable; the next capture refreshes anyway.
        pass


def _on_directing_update(self, context):
    """Directing entry: refresh the surface and reconcile the watched shot.

    All four entry operators set ``is_directing = True``; none of them
    causes a depsgraph update, so without an explicit request the strip
    ignores natively keyed cameras until an unrelated edit ticks the
    beat_sync handler.
    """
    _redraw_director_surface(self, context)
    if self.is_directing:
        _request_beat_reconcile()


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
        # The topbar Director toggle lives in a global area, which screen
        # iteration misses; global_areas is a Mixar RNA addition.
        for area in getattr(window, "global_areas", ()):
            area.tag_redraw()


class MixarDirectorBeat(PropertyGroup):
    """One sparse camera pose and its captured moodboard still."""

    beat_id: StringProperty(name="Beat ID", default="")
    frame: IntProperty(name="Frame", default=1, min=-1048574, max=1048574)
    image: PointerProperty(
        name="Reference Frame",
        description="Packed viewport capture associated with this keyframe",
        type=bpy.types.Image,
    )


class MixarDirectorRenderOutput(PropertyGroup):
    """One persistent motion-guide movie produced from a Director shot."""

    output_id: StringProperty(name="Output ID", default="")
    kind: EnumProperty(
        name="Render Type",
        items=SHOT_RENDER_OUTPUT_ITEMS,
        default="CLAY",
    )
    image: PointerProperty(
        name="Moodboard Video",
        description="Persistent movie datablock placed on the Moodboard",
        type=bpy.types.Image,
    )
    rendered_at: StringProperty(name="Rendered At", default="", maxlen=64)


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
        description="Describe the action and motion to generate between keyframes",
        default="",
        maxlen=4096,
        options={'TEXTEDIT_UPDATE'},
    )
    guidance_strength: EnumProperty(
        name="Adherence",
        description="How closely the generated video should follow the keyframes",
        items=GUIDANCE_STRENGTH_ITEMS,
        default="BALANCED",
    )
    handheld: BoolProperty(
        name="Handheld",
        description=(
            "Add organic handheld drift on top of the captured camera path. "
            "Keyframes stay clean; the texture rides the evaluated camera "
            "into previews, guide videos, and sampled guidance"
        ),
        default=False,
        update=_on_handheld_update,
    )
    handheld_strength: FloatProperty(
        name="Handheld Intensity",
        description="How much the handheld camera drifts and trembles",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        update=_on_handheld_update,
    )
    camera_template: EnumProperty(
        name="Template Style",
        description="Named movement style applied to this shot",
        items=CAMERA_TEMPLATE_ITEMS,
        default="NONE",
    )
    render_output_types: EnumProperty(
        name="Video Renders",
        description="Shot videos to render and add to the Moodboard",
        items=SHOT_RENDER_OUTPUT_ITEMS,
        options={'ENUM_FLAG'},
        default={'CLAY'},
    )
    render_resolution_percentage: IntProperty(
        name="Resolution",
        description="Percentage of the scene output resolution used for shot videos",
        default=50,
        min=25,
        max=100,
        subtype='PERCENTAGE',
    )
    render_outputs: CollectionProperty(
        type=MixarDirectorRenderOutput,
        name="Rendered Videos",
    )
    render_is_running: BoolProperty(
        name="Rendering Shot",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    render_progress: FloatProperty(
        name="Render Progress",
        default=0.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    render_status: StringProperty(
        name="Render Status",
        default="",
        maxlen=256,
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    beats: CollectionProperty(type=MixarDirectorBeat, name="Keyframes")
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
    active_shot_index: IntProperty(
        name="Active Shot",
        default=0,
        min=0,
        update=_on_active_shot_change,
    )
    beat_seconds: FloatProperty(
        name="Keyframe Spacing",
        description="Time automatically placed between captured keyframes",
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
        update=_on_directing_update,
    )
    ruler_unit: EnumProperty(
        name="Ruler Unit",
        description="How the timeline ruler labels time",
        items=(
            ("MIN", "Min", "Label the ruler in minutes and seconds", 0),
            ("SEC", "Sec", "Label the ruler in seconds", 1),
        ),
        default="SEC",
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
            (
                "EXPLORE",
                "Explore",
                "Fly the viewport freely without moving the shot camera",
                2,
            ),
        ),
        default="NAVIGATE",
        options={'SKIP_SAVE'},
    )
    animation_seconds: FloatProperty(
        name="Motion Length",
        description="How long a character animation preset lasts",
        default=2.0,
        min=0.5,
        max=10.0,
        step=10,
        precision=1,
        subtype='TIME',
    )
    show_trajectory: BoolProperty(
        name="Path",
        description=(
            "Draw the shot camera's trajectory over the scene while "
            "directing — keyframes in green, the playhead position in blue"
        ),
        default=True,
        update=_redraw_director_surface,
    )
    level_horizon: BoolProperty(
        name="Fix Z",
        description=(
            "Keep the horizon level while navigating: the camera's roll is "
            "removed when Navigate starts and WASD walking never adds roll"
        ),
        default=True,
    )
    auto_key: BoolProperty(
        name="Auto Key",
        description=(
            "Automatically capture a keyframe after every camera move "
            "instead of pressing F or Capture Keyframe"
        ),
        default=False,
        update=_redraw_director_surface,
    )


classes = (
    MixarDirectorBeat,
    MixarDirectorRenderOutput,
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

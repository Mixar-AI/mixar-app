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
    BEAT_INTERPOLATION_DEFAULT,
    BEAT_INTERPOLATION_ITEMS,
    CAMERA_TEMPLATE_ITEMS,
    DEFAULT_BEAT_SECONDS,
    DEFAULT_SPEED,
    GUIDANCE_STRENGTH_ITEMS,
    INTERPOLATION_ITEMS,
    MAX_BEAT_SECONDS,
    MIN_BEAT_SECONDS,
    SHOT_RENDER_OUTPUT_ITEMS,
    SHOT_STATE_ITEMS,
    SPEED_MAX,
    SPEED_MIN,
)
from ...core.property_updates import (
    _activate_shot_camera,
    _get_auto_key,
    _get_range_end_seconds,
    _get_range_start_seconds,
    _set_range_end_seconds,
    _set_range_start_seconds,
    _camera_poll,
    _on_beat_interpolation_update,
    _on_active_shot_change,
    _on_directing_update,
    _on_handheld_update,
    _on_interpolation_update,
    _on_speed_update,
    _on_track_target_update,
    _redraw_director_surface,
    _set_auto_key,
    _track_target_poll,
)


class MixarDirectorBeat(PropertyGroup):
    """One sparse camera pose and its captured moodboard still."""

    beat_id: StringProperty(name="Beat ID", default="")
    frame: IntProperty(name="Frame", default=1, min=-1048574, max=1048574)
    # The frame at shot speed 0; `core/retime.py` derives `frame` from it
    # (never the reverse). 0.0 on a non-zero frame = unrecorded (old file).
    time_base: FloatProperty(
        name="Time Base",
        default=0.0,
        options={'HIDDEN'},
    )
    image: PointerProperty(
        name="Reference Frame",
        description="Packed viewport capture associated with this keyframe",
        type=bpy.types.Image,
    )
    # A keyframe's interpolation governs the segment FROM it TO the next one,
    # so this IS "the easing between these two keyframes". Resting on SHOT
    # keeps a take easing one way by default; an override changes one span.
    interpolation: EnumProperty(
        name="Interpolation",
        description="How the camera eases from this keyframe to the next one",
        items=BEAT_INTERPOLATION_ITEMS,
        default=BEAT_INTERPOLATION_DEFAULT,
        update=_on_beat_interpolation_update,
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


class MixarDirectorCameraOutput(PropertyGroup):
    """The aspect ratio a camera remembers as its own.

    Blender has one render size and it belongs to the SCENE — there is no
    per-camera resolution to bind to. A director works the other way round:
    the 2.39:1 hero shot and the 9:16 social cutdown are two cameras in one
    scene, and a ratio picked for one must not silently reshape the other. So
    the ratio is remembered here and written into `scene.render` whenever this
    camera becomes the live one (`core/aspect.apply_camera_ratio`); the scene
    stays the single source of truth for what actually renders.

    ``configured`` is what keeps an untouched camera from snapping the frame to
    a default nobody chose: until a ratio is picked for it, switching to this
    camera leaves the scene's shape alone.
    """

    aspect_x: IntProperty(name="Ratio Width", default=16, min=1, max=100000)
    aspect_y: IntProperty(name="Ratio Height", default=9, min=1, max=100000)
    configured: BoolProperty(
        name="Has Its Own Aspect",
        description="A ratio has been chosen for this camera",
        default=False,
    )


class MixarDirectorShot(PropertyGroup):
    """A take on a native Blender scene and camera."""

    shot_id: StringProperty(name="Shot ID", default="")
    name: StringProperty(name="Shot", default="Shot 01", maxlen=128)
    version: IntProperty(name="Take", default=1, min=1)
    parent_shot_id: StringProperty(name="Parent Shot ID", default="")
    state: EnumProperty(name="State", items=SHOT_STATE_ITEMS, default="DRAFT")
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
    interpolation: EnumProperty(
        name="Interpolation",
        description=(
            "How the camera eases between this shot's keyframes, wherever a "
            "keyframe has not chosen for itself"
        ),
        items=INTERPOLATION_ITEMS,
        default="BEZIER",
        update=_on_interpolation_update,
    )
    # Cinema Mode Speed slider: intervals scale by 2 ** (-speed) around the
    # first keyframe (`core/retime.py`); 0 in the middle is as captured.
    speed: FloatProperty(
        name="Speed",
        description=(
            "Speed of the camera through this shot: right contracts the "
            "shot (faster), left expands it (slower); the middle is the "
            "timing as captured"
        ),
        default=DEFAULT_SPEED,
        min=SPEED_MIN,
        max=SPEED_MAX,
        soft_min=SPEED_MIN,
        soft_max=SPEED_MAX,
        step=5,
        precision=2,
        update=_on_speed_update,
    )
    track_target: PointerProperty(
        name="Track Target",
        description="Object the shot camera keeps pointing at (Track To constraint)",
        type=bpy.types.Object,
        poll=_track_target_poll,
        update=_on_track_target_update,
    )
    camera_template: EnumProperty(
        name="Template Style",
        description="Named movement style applied to this shot",
        items=CAMERA_TEMPLATE_ITEMS,
        default="NONE",
    )
    export_images: BoolProperty(
        name="Keyframe Images",
        description="Add each keyframe's captured image to the Moodboard",
        default=True,
    )
    render_output_types: EnumProperty(
        name="Videos",
        description="Videos of this shot to render into the Moodboard",
        items=SHOT_RENDER_OUTPUT_ITEMS,
        options={'ENUM_FLAG'},
        default={'CLAY'},
    )
    render_resolution_percentage: IntProperty(
        name="Video Size",
        description="Size of the videos, as a percentage of the scene's output size",
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
    # The Custom aspect fields, edited in the aspect popup itself.
    #
    # They live on the state rather than on the operator because the operator
    # used `invoke_props_dialog`, which is Blender's STOCK dialog — grey
    # chrome, OK/Cancel, nothing like the glass popup it opened from. A ratio
    # is two numbers; two numbers belong in the popup.
    custom_aspect_x: IntProperty(
        name="Width",
        description="Width side of a custom ratio",
        default=16,
        min=1,
        max=100000,
    )
    custom_aspect_y: IntProperty(
        name="Height",
        description="Height side of a custom ratio",
        default=9,
        min=1,
        max=100000,
    )
    ruler_unit: EnumProperty(
        name="Ruler Unit",
        description="How the timeline ruler labels the shot",
        # The choice a director actually has is FRAMES or elapsed time, not
        # two spellings of elapsed time. Minutes-versus-seconds was a format
        # detail the ruler can decide for itself from how long the shot is.
        items=(
            ("FRAMES", "Frames", "Label the ruler with frame numbers", 0),
            (
                "DURATION",
                "Duration",
                "Label the ruler with elapsed time",
                1,
            ),
        ),
        default="DURATION",
    )
    # The dock's Start/End fields read in the unit the switch beside them
    # selects, so DURATION needs the scene's range as a time. These are
    # mirrors, not state: nothing is stored, every read and write goes
    # straight through to `scene.frame_start` / `scene.frame_end`, which is
    # what keeps them correct when the range is changed from anywhere else.
    range_start_seconds: FloatProperty(
        name="Start",
        description="First frame of the scene range, in seconds",
        unit='TIME_ABSOLUTE',
        get=_get_range_start_seconds,
        set=_set_range_start_seconds,
    )
    range_end_seconds: FloatProperty(
        name="End",
        description="Last frame of the scene range, in seconds",
        unit='TIME_ABSOLUTE',
        get=_get_range_end_seconds,
        set=_set_range_end_seconds,
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
            ("EXPLORE", "Explore",
             "Fly the viewport freely without moving the shot camera", 2),
            ("AERIAL", "Aerial",
             "Look down on the scene from above and click to place the camera", 3),
        ),
        default="NAVIGATE",
        options={'SKIP_SAVE'},
    )
    walk_active: BoolProperty(
        name="Walking",
        description=(
            "Blender's own walk navigation is running. Session state, not a "
            "setting: the Cinema top strip swaps its shortcut hints for "
            "walk's own while it is on"
        ),
        default=False,
        options={'SKIP_SAVE'},
        update=_redraw_director_surface,
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
    level_horizon: BoolProperty(
        name="Fix Z",
        description=(
            "Keep the horizon level while navigating: the camera's roll is "
            "removed when Navigate starts and WASD walking never adds roll"
        ),
        default=True,
    )
    walk_stop_requested: BoolProperty(
        name="Stop Walking",
        description=(
            "Ask the running Cinema walk to finish. The native walk clears "
            "it on the tick it stops"
        ),
        default=False,
        options={'SKIP_SAVE'},
    )
    recording: BoolProperty(
        name="Recording",
        description=(
            "Read-only: a take is being laid down right now — Auto Key is on, "
            "the timeline is playing, and something is driving the camera"
        ),
        default=False,
        options={'SKIP_SAVE'},
        update=_redraw_director_surface,
    )
    # Blender's own Auto Keying, not a copy of it: see
    # `core/property_updates.py` (`_get_auto_key` / `_set_auto_key`).
    auto_key: BoolProperty(
        name="Auto Keying",
        description=(
            "Blender's Auto Keying (the Timeline's record button): key the "
            "camera after every move, and record a take while the timeline plays"
        ),
        get=_get_auto_key,
        set=_set_auto_key,
        update=_redraw_director_surface,
    )


classes = (
    MixarDirectorBeat,
    MixarDirectorCameraOutput,
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
    # On the camera DATA, not the object: a ratio belongs to the lens the
    # director framed with, and it travels with the camera into another file.
    bpy.types.Camera.mixar_director_output = PointerProperty(
        type=MixarDirectorCameraOutput,
        name="Mixar Output",
        description="Output aspect ratio this camera frames for",
    )


def unregister():
    if hasattr(bpy.types.Camera, "mixar_director_output"):
        del bpy.types.Camera.mixar_director_output
    if hasattr(bpy.types.Scene, "mixar_director"):
        del bpy.types.Scene.mixar_director
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass

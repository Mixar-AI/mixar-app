# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Context-safe native 3D viewport and camera-session helpers."""

from __future__ import annotations

import bpy

from ..constants import DIRECTOR_CAMERA_BASENAME


_VIEW_STATES: dict[int, dict] = {}


def _scene_key(scene) -> int:
    try:
        return int(scene.as_pointer())
    except Exception:
        return id(scene)


def _live_id(reference):
    """Return *reference* only while its underlying ID is still alive.

    ``_VIEW_STATES`` keeps Python ID references for an entire directing
    session. Deleting the datablock meanwhile (outliner delete, undo
    swapping Main) frees the StructRNA underneath, after which any attribute
    access raises ``ReferenceError: StructRNA ... has been removed``.
    """
    if reference is None:
        return None
    try:
        reference.name
    except ReferenceError:
        return None
    return reference


def find_view3d_context(context):
    """Return ``(window, area, window_region, space)`` for a 3D viewport."""
    current_area = getattr(context, "area", None)
    current_window = getattr(context, "window", None)
    if current_area is not None and current_area.type == 'VIEW_3D':
        region = next(
            (item for item in current_area.regions if item.type == 'WINDOW'),
            None,
        )
        if region is not None:
            return current_window, current_area, region, current_area.spaces.active

    best = None
    best_size = -1
    for window in getattr(context.window_manager, "windows", ()):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()):
            if area.type != 'VIEW_3D':
                continue
            region = next(
                (item for item in area.regions if item.type == 'WINDOW'),
                None,
            )
            size = area.width * area.height
            if region is not None and size > best_size:
                best = (window, area, region, area.spaces.active)
                best_size = size
    return best


def create_camera_from_view(context):
    """Create a native camera aligned to the current viewport."""
    target = find_view3d_context(context)
    if target is None:
        raise RuntimeError("No 3D viewport is available")
    _window, _area, _region, space = target
    camera_data = bpy.data.cameras.new(DIRECTOR_CAMERA_BASENAME)
    camera = bpy.data.objects.new(DIRECTOR_CAMERA_BASENAME, camera_data)
    context.scene.collection.objects.link(camera)
    camera.matrix_world = space.region_3d.view_matrix.inverted()
    camera.data.show_passepartout = True
    camera.data.passepartout_alpha = 0.8
    camera.data.show_composition_thirds = True
    return camera


def remember_view(context, scene) -> None:
    target = find_view3d_context(context)
    if target is None or _scene_key(scene) in _VIEW_STATES:
        return
    _window, _area, _region, space = target
    region_3d = space.region_3d
    local_camera = getattr(space, "camera", None)
    _VIEW_STATES[_scene_key(scene)] = {
        "view_perspective": region_3d.view_perspective,
        "view_location": region_3d.view_location.copy(),
        "view_rotation": region_3d.view_rotation.copy(),
        "view_distance": region_3d.view_distance,
        "lock_camera": space.lock_camera,
        "local_camera": local_camera,
        # Undo can free-and-recreate the object; the name recovers it then.
        "local_camera_name": getattr(local_camera, "name", ""),
        "chrome": {
            name: getattr(space, name)
            for name in (
                "show_region_ui",
                "show_region_toolbar",
                "show_region_hud",
            )
            if hasattr(space, name)
        },
    }


def enter_director_surface(context):
    """Enter the calm viewport shell used by the native Director UI."""
    target = find_view3d_context(context)
    if target is None:
        raise RuntimeError("No 3D viewport is available")
    _window, area, _region, space = target
    remember_view(context, context.scene)
    # Only toggle a region that is actually open: setting show_region_* to a
    # value it already holds still re-runs Blender's show/hide animation, which
    # is the N-panel flash seen when entering or leaving Director.
    for name in ("show_region_ui", "show_region_toolbar", "show_region_hud"):
        if hasattr(space, name) and getattr(space, name):
            setattr(space, name, False)
    area.tag_redraw()
    return target


def enter_camera_view(context, camera, *, remember: bool = True):
    """Make *camera* the scene camera and enter lock-to-camera view."""
    target = find_view3d_context(context)
    if target is None:
        raise RuntimeError("No 3D viewport is available")
    _window, area, _region, space = target
    if remember:
        remember_view(context, context.scene)
    context.scene.camera = camera
    if hasattr(space, "camera"):
        space.camera = camera
    space.region_3d.view_perspective = 'CAMERA'
    space.lock_camera = True
    # Camera view and free-fly exploration are mutually exclusive; every
    # path back into a camera (shot switch, keyframe jump, new take) must
    # end Explore or the overlay keeps offering Add Camera Here in-frame.
    state = getattr(context.scene, "mixar_director", None)
    if state is not None and state.navigation_mode == 'EXPLORE':
        state.navigation_mode = 'NAVIGATE'
    area.tag_redraw()
    return target


def enter_free_view(context):
    """Leave camera lock so navigation moves the viewpoint, not the camera."""
    target = find_view3d_context(context)
    if target is None:
        raise RuntimeError("No 3D viewport is available")
    _window, area, _region, space = target
    space.lock_camera = False
    if space.region_3d.view_perspective == 'CAMERA':
        space.region_3d.view_perspective = 'PERSP'
    area.tag_redraw()
    return target


def invoke_explore_walk(context):
    """Fly the viewport with WASD walk while no camera is being driven.

    Generated worlds import at a scale where orbit/zoom alone cannot reach
    an interior vantage point comfortably; walk is the travel tool. The
    shot camera stays untouched — Add Camera Here captures the view later.
    """
    target = enter_free_view(context)
    window, area, region, space = target
    with context.temp_override(
        window=window,
        area=area,
        region=region,
        space_data=space,
    ):
        return bpy.ops.view3d.walk('INVOKE_DEFAULT'), target


def restore_view(context, scene) -> None:
    """Restore the viewport that existed before the directing session."""
    state = _VIEW_STATES.pop(_scene_key(scene), None)
    target = find_view3d_context(context)
    if state is None or target is None:
        return
    _window, area, _region, space = target
    region_3d = space.region_3d
    space.lock_camera = state["lock_camera"]
    if hasattr(space, "camera"):
        camera = _live_id(state.get("local_camera"))
        if camera is None and state.get("local_camera_name"):
            camera = bpy.data.objects.get(state["local_camera_name"])
        try:
            space.camera = camera
        except Exception:
            # A dead reference must not strand the viewport half-restored:
            # the chrome and view restore below still have to run.
            pass
    for name, value in state.get("chrome", {}).items():
        if hasattr(space, name) and getattr(space, name) != value:
            setattr(space, name, value)
    region_3d.view_perspective = state["view_perspective"]
    if state["view_perspective"] != 'CAMERA':
        region_3d.view_location = state["view_location"]
        region_3d.view_rotation = state["view_rotation"]
        region_3d.view_distance = state["view_distance"]
    area.tag_redraw()


def level_camera_horizon(camera) -> bool:
    """Remove camera roll while preserving the view direction ("Fix Z").

    Walk navigation never adds roll, but it preserves any roll the camera
    already carries, which leaves directors stuck slightly tilted with no
    obvious way back to level. Skips near-vertical views where "level" is
    undefined.
    """
    from mathutils import Vector

    matrix = camera.matrix_world
    forward = -Vector((matrix[0][2], matrix[1][2], matrix[2][2]))
    if forward.length < 1e-6:
        return False
    forward.normalize()
    if abs(forward.z) > 0.999:
        return False
    leveled = forward.to_track_quat('-Z', 'Y').to_matrix().to_4x4()
    leveled.translation = matrix.translation.copy()
    camera.matrix_world = leveled
    return True


def invoke_walk(context, camera):
    """Invoke Blender's native WASD walk navigation in camera view.

    Returns ``(result, target)`` where target is the ``(window, area,
    region, space)`` tuple the walk was started in, so callers can
    supervise the running navigation.
    """
    target = enter_camera_view(context, camera, remember=False)
    window, area, region, space = target
    space.lock_camera = True
    state = getattr(context.scene, "mixar_director", None)
    if state is not None and getattr(state, "level_horizon", False):
        level_camera_horizon(camera)
    with context.temp_override(
        window=window,
        area=area,
        region=region,
        space_data=space,
    ):
        return bpy.ops.view3d.walk('INVOKE_DEFAULT'), target


def select_camera_object(context, camera) -> None:
    """Make *camera* the only selected, active object in the view layer.

    Precise gizmos and transform hotkeys follow the selection, so every
    deliberate switch of the directed camera must hand it over — otherwise
    a gizmo drag or G/R keeps editing the previous shot's camera. Called
    from shot/camera switches only, never from plain view entry: captures
    re-enter the camera view too, and stealing the selection there would
    break flows that act on the selected object (character Animation
    presets).
    """
    view_layer = getattr(context, "view_layer", None)
    objects = getattr(view_layer, "objects", None)
    if objects is None or camera is None:
        return
    try:
        for obj in list(getattr(objects, "selected", ()) or ()):
            obj.select_set(False)
        camera.select_set(True)
        objects.active = camera
    except (AttributeError, RuntimeError, ReferenceError):
        # Not linked into the active view layer (cross-scene shot) or a
        # dying reference during load/undo — selection is meaningless then.
        pass


def enter_precise_mode(context, camera) -> None:
    """Select the camera and expose native transform gizmos."""
    _window, area, _region, space = enter_camera_view(
        context, camera, remember=False,
    )
    space.lock_camera = False
    select_camera_object(context, camera)
    space.show_gizmo = True
    for attr in ("show_gizmo_object_translate", "show_gizmo_object_rotate"):
        if hasattr(space, attr):
            setattr(space, attr, True)
    area.tag_redraw()


def clear_runtime_state() -> None:
    _VIEW_STATES.clear()

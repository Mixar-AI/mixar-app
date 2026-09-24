# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Object tracking for a shot camera.

``shot.track_target`` names the object the camera keeps pointing at. The
mechanism is Blender's own Track To constraint on the camera (negative Z
forward, Y up, the classic camera setup), owned by name so Director can
refresh or remove exactly its own constraint and never a user's. Captured
rotation keys stay on the camera underneath the constraint, so clearing the
target returns the take to its keyed framing.
"""

import bpy

from ..constants import TRACK_CONSTRAINT_NAME
from .shot_api import shot_scene

#: Custom property marking an empty Director created to aim at.
FOCUS_MARKER = "mixar_director_focus"
#: Base name for those empties; Blender uniquifies it.
FOCUS_BASENAME = "Mixar Focus"
#: Below this the origin IS the centre and no helper is worth creating.
FOCUS_EPSILON = 1.0e-4


def find_track_constraint(camera):
    constraints = getattr(camera, "constraints", None)
    if constraints is None:
        return None
    return constraints.get(TRACK_CONSTRAINT_NAME)


def is_focus_empty(obj) -> bool:
    """Whether *obj* is one of Director's aim helpers."""
    try:
        return bool(obj is not None and obj.get(FOCUS_MARKER))
    except (AttributeError, TypeError):
        return False


def local_centre(obj):
    """The centre of *obj*'s bounding box, in its OWN local space.

    ``None`` when the object carries no geometry, or when its origin already
    IS its centre — a helper would then aim at exactly the same point.
    """
    from mathutils import Vector

    box = getattr(obj, "bound_box", None)
    if not box:
        return None
    corners = [Vector(corner) for corner in box]
    if not corners:
        return None
    centre = sum(corners, Vector((0.0, 0.0, 0.0))) / len(corners)
    return None if centre.length <= FOCUS_EPSILON else centre


def _focus_used_elsewhere(empty, exclude_camera) -> bool:
    """Whether another object still aims at *empty*."""
    for obj in bpy.data.objects:
        if obj == exclude_camera or obj == empty:
            continue
        for constraint in getattr(obj, "constraints", ()):
            if getattr(constraint, "target", None) == empty:
                return True
    return False


def _remove_focus_empty(empty, exclude_camera=None) -> None:
    if not is_focus_empty(empty) or _focus_used_elsewhere(empty, exclude_camera):
        return
    bpy.data.objects.remove(empty, do_unlink=True)


def ensure_focus_empty(scene, target):
    """An empty at *target*'s visual centre, parented to it, or ``None``.

    A Track To constraint aims at its target's ORIGIN, and an origin is very
    often nowhere near the middle of the thing — the feet of a character, the
    world origin of an imported mesh. Aiming there keeps the object in shot
    and NOT centred, which is what "the camera is not centering the object"
    means.

    So Director aims at a helper instead: an empty PARENTED to the target at
    the bounding box's centre in the target's own local space, which follows
    it through every move, rotation and animation for free.

    It is not hidden, it is drawn at zero size: a constraint target must keep
    evaluating, and `hide_viewport` is the one flag that can stop it. It is
    unselectable and never rendered, and the aerial map already ignores
    empties.
    """
    centre = local_centre(target)
    if centre is None:
        return None
    existing = None
    for child in getattr(target, "children", ()):
        if is_focus_empty(child):
            existing = child
            break
    empty = existing
    if empty is None:
        empty = bpy.data.objects.new(f"{FOCUS_BASENAME} {target.name}", None)
        empty[FOCUS_MARKER] = True
        scene.collection.objects.link(empty)
        empty.parent = target
    empty.empty_display_size = 0.0
    empty.hide_render = True
    empty.hide_select = True
    empty.location = centre
    return empty


def clear_tracking(camera) -> bool:
    """Remove Director's tracking constraint from *camera*, if present."""
    constraint = find_track_constraint(camera)
    if constraint is None:
        return False
    aimed_at = getattr(constraint, "target", None)
    camera.constraints.remove(constraint)
    # The helper exists only to be aimed at; nothing else should keep it.
    _remove_focus_empty(aimed_at, exclude_camera=camera)
    return True


def refresh_tracking(shot) -> bool:
    """Make the camera's constraint agree with ``shot.track_target``.

    Returns True while tracking is live afterwards.
    """
    camera = getattr(shot, "camera", None)
    target = getattr(shot, "track_target", None)
    if camera is None:
        return False
    if target is None or target == camera:
        clear_tracking(camera)
        return False
    scene = shot_scene(shot, getattr(bpy.context, "scene", None))
    # Aim at the target's visual centre when its origin is not already there.
    aim = ensure_focus_empty(scene, target) if scene is not None else None
    constraint = find_track_constraint(camera)
    if constraint is None:
        constraint = camera.constraints.new('TRACK_TO')
        constraint.name = TRACK_CONSTRAINT_NAME
    previous = getattr(constraint, "target", None)
    constraint.target = aim or target
    if previous is not None and previous != constraint.target:
        _remove_focus_empty(previous, exclude_camera=camera)
    constraint.track_axis = 'TRACK_NEGATIVE_Z'
    constraint.up_axis = 'UP_Y'
    constraint.mute = False
    return True


def pick_object_under_cursor(context, region, region_3d, coord):
    """The scene object under a region-space *coord*, or ``None``.

    A depsgraph ray cast rather than a selection click: picking must not
    disturb the selection Director keeps on the shot camera.
    """
    from bpy_extras import view3d_utils

    origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coord)
    depsgraph = context.evaluated_depsgraph_get()
    hit, _location, _normal, _index, obj, _matrix = context.scene.ray_cast(
        depsgraph, origin, direction
    )
    if not hit or obj is None:
        return None
    return getattr(obj, "original", obj)


# -------------------------------------------------------------------------
# The picked object's extent.
#
# Tracking itself only aims; nothing here moves the camera or touches its
# lens. Depth of field reads the sphere's centre to focus on the middle of a
# picked subject rather than its origin (`core/dof.py`).


def world_bounding_sphere(obj):
    """Centre and radius of *obj*'s world bounding box, or ``None``.

    Read from the object's own `bound_box`, which is in local space, through
    its world matrix — so a scaled or rotated object gives a sphere that
    actually contains it.
    """
    from mathutils import Vector

    box = getattr(obj, "bound_box", None)
    if not box:
        return None
    matrix = obj.matrix_world
    corners = [matrix @ Vector(corner) for corner in box]
    if not corners:
        return None
    centre = sum(corners, Vector((0.0, 0.0, 0.0))) / len(corners)
    radius = max((corner - centre).length for corner in corners)
    return centre, radius

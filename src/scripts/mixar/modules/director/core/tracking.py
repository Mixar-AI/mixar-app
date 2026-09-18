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

from ..constants import TRACK_CONSTRAINT_NAME


def find_track_constraint(camera):
    constraints = getattr(camera, "constraints", None)
    if constraints is None:
        return None
    return constraints.get(TRACK_CONSTRAINT_NAME)


def clear_tracking(camera) -> bool:
    """Remove Director's tracking constraint from *camera*, if present."""
    constraint = find_track_constraint(camera)
    if constraint is None:
        return False
    camera.constraints.remove(constraint)
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
    constraint = find_track_constraint(camera)
    if constraint is None:
        constraint = camera.constraints.new('TRACK_TO')
        constraint.name = TRACK_CONSTRAINT_NAME
    constraint.target = target
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

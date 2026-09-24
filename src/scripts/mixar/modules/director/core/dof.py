# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Depth of field for a shot camera.

Blender already owns the optics: ``camera.data.dof`` carries ``use_dof``,
``aperture_fstop``, ``focus_distance`` and ``focus_object``, and the Cinema
popup binds those properties directly so no range or unit is restated. What
lives here is the one thing a director means by "focus" that Blender does not
offer as a property — *focus on THAT* — plus the rule that makes clearing a
focus object leave the image where it was instead of snapping to a stale
distance.

Focus follows the object: ``focus_object`` is evaluated every frame, so a
subject that moves stays sharp with no keyframes at all. That is why Director
does not key depth of field — the common case needs no keys, and the ones that
do are a focus pull the director can key natively.
"""

from __future__ import annotations

#: The f-stop slider's TRAVEL. Mirrors FSTOP_SLIDER_MIN / _MAX in
#: `director/constants.py` and FSTOP_SLIDER_* in `view3d_director_cinema.hh`.
FSTOP_MIN = 0.95
FSTOP_MAX = 22.0


def camera_dof(camera):
    """``camera.data.dof``, or ``None`` when *camera* is not a camera."""
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        return None
    return getattr(getattr(camera, "data", None), "dof", None)


def focus_distance_to(camera, target) -> float | None:
    """Distance from *camera* to *target*'s visual centre, or ``None``.

    The centre of the bounding sphere, not the origin: an origin is very
    often nowhere near the middle of the thing (the feet of a character, the
    world origin of an imported mesh), and focusing there puts the plane of
    focus in front of or behind the subject.
    """
    from .tracking import world_bounding_sphere

    try:
        sphere = world_bounding_sphere(target)
        centre = sphere[0] if sphere is not None else target.matrix_world.translation
        distance = (centre - camera.matrix_world.translation).length
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return None
    return float(distance) if distance > 0.0 else None


def set_focus_object(camera, target) -> bool:
    """Focus *camera* on *target* and switch depth of field on.

    Returns whether anything was set. The distance is recorded as well as the
    object: Blender ignores ``focus_distance`` while an object is set, but
    clearing the object later must not drop the image back to a stale number.
    """
    dof = camera_dof(camera)
    if dof is None or target is None or target == camera:
        return False
    distance = focus_distance_to(camera, target)
    if distance is not None:
        dof.focus_distance = distance
    dof.focus_object = target
    dof.use_dof = True
    return True


def clear_focus_object(camera) -> bool:
    """Drop the focus object, holding the distance it was focusing at.

    Returns whether an object was cleared. Without the measurement the image
    would jump the moment the object is released, to whatever
    ``focus_distance`` last happened to hold.
    """
    dof = camera_dof(camera)
    if dof is None or getattr(dof, "focus_object", None) is None:
        return False
    distance = focus_distance_to(camera, dof.focus_object)
    if distance is not None:
        dof.focus_distance = distance
    dof.focus_object = None
    return True

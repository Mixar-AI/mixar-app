# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Slotted-action-safe F-curve access for Director's camera animation.

Blender 5 stores animation in layered actions with per-slot channelbags
and no longer exposes the legacy ``Action.fcurves`` collection. Every
Director read or removal of camera F-curves goes through these helpers,
which resolve the assigned slot's channelbag and fall back to the legacy
collection only for actions loaded from older files.
"""

from __future__ import annotations


def _fcurve_collection(animated_id):
    """The editable F-curve collection driving *animated_id*, or ``None``."""
    animation_data = getattr(animated_id, "animation_data", None)
    action = getattr(animation_data, "action", None)
    if action is None:
        return None
    try:
        from bpy_extras.anim_utils import (
            animdata_get_channelbag_for_assigned_slot,
        )

        channelbag = animdata_get_channelbag_for_assigned_slot(animation_data)
    except (AttributeError, ImportError, RuntimeError):
        channelbag = None
    if channelbag is not None:
        return channelbag.fcurves
    # Compatibility for legacy actions opened from older Blender versions.
    return getattr(action, "fcurves", None)


def assigned_fcurves(animated_id) -> tuple:
    """All F-curves currently driving *animated_id*."""
    collection = _fcurve_collection(animated_id)
    return tuple(collection) if collection is not None else ()


def remove_fcurves(animated_id, data_paths) -> int:
    """Delete every F-curve of *animated_id* whose path is in *data_paths*."""
    collection = _fcurve_collection(animated_id)
    if collection is None:
        return 0
    stale = [fcurve for fcurve in collection if fcurve.data_path in data_paths]
    for fcurve in stale:
        collection.remove(fcurve)
    return len(stale)

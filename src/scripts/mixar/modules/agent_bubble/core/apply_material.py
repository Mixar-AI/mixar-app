# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Apply a library MATERIAL to the selected objects (the Library tab's
"Apply to Selected", and a material tile's Add in a multi-selection).

A material has no place in the scene of its own, so where an object asset is
appended and framed (``spawn_asset.py``), a material is appended once and
assigned:

* reused when this file already appended it from the same library file
  (``library_weak_reference``), so repeated applies never pile up ``.001``
  copies;
* assigned to each selected object's ACTIVE slot (a slot is added when the
  object has none) — what dropping a material onto an object does;
* never over a Mixar Paint layer stack: a plain material would discard the
  painted layers, so such objects are skipped and named in the message. The
  agent's ``apply_library_material`` tool has the same guard.

Selection is read from the 3D viewport's view layer, not the island window's
context, which has no meaningful selection of its own.
"""

from __future__ import annotations

import logging
import os

import bpy

from mixar.modules.common.i18n import n_, rpt_

logger = logging.getLogger(__name__)

_MATERIAL_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME"}


def has_layer_stack(material) -> bool:
    """Does ``material`` hold a Mixar Paint layer stack (a group with channels)?"""
    tree = getattr(material, "node_tree", None) if material is not None else None
    for node in getattr(tree, "nodes", ()) or ():
        group = getattr(node, "node_tree", None)
        props = getattr(group, "mp", None) if group is not None else None
        if props is not None and len(getattr(props, "channels", ()) or ()) > 0:
            return True
    return False


def split_targets(objects):
    """(targets, layered): objects that can take a material, and those skipped
    because a slot holds a Mixar Paint layer stack."""
    targets, layered = [], []
    for obj in objects:
        if getattr(obj, "type", "") not in _MATERIAL_TYPES or getattr(obj, "data", None) is None:
            continue
        if any(has_layer_stack(slot.material) for slot in obj.material_slots):
            layered.append(obj)
        else:
            targets.append(obj)
    return targets, layered


def assign_to_active_slot(obj, material):
    """Put ``material`` in ``obj``'s active slot, adding one if it has none."""
    if len(obj.material_slots) == 0:
        obj.data.materials.append(material)
    else:
        obj.material_slots[obj.active_material_index].material = material


def _norm(path):
    return os.path.normcase(os.path.abspath(bpy.path.abspath(path)))


def _already_appended(blend_path, name):
    want = _norm(blend_path)
    for mat in bpy.data.materials:
        ref = getattr(mat, "library_weak_reference", None)
        if mat.library is None and ref is not None and ref.id_name == "MA" + name:
            if _norm(ref.filepath) == want:
                return mat
    return None


def _append(blend_path, name):
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        if name not in data_from.materials:
            return None
        data_to.materials = [name]
    return data_to.materials[0] if data_to.materials else None


def apply_library_material(context, blend_path, asset_name):
    """Apply ``asset_name`` from ``blend_path`` to the viewport selection.

    Returns ``(ok, message)``.
    """
    from mixar.modules.agent_bubble.core.spawn_asset import _redraw, _viewport_target

    blend = (blend_path or "").strip()
    name = (asset_name or "").strip()
    if not blend or not name:
        return False, n_("That asset has no file on disk")
    if not os.path.isfile(blend):
        return False, n_("The asset's .blend is missing")

    target = _viewport_target(context)
    if target is None or target.view_layer is None:
        return False, n_("No scene is open to apply this to")
    view_layer = target.view_layer
    selected = [o for o in view_layer.objects if o.select_get(view_layer=view_layer)]
    if not selected:
        return False, n_("Select the objects to apply this material to")
    targets, layered = split_targets(selected)
    if not targets:
        if layered:
            return False, n_("The selection is painted with Mixar Paint layers; "
                             "its material was not replaced")
        return False, n_("None of the selected objects can hold a material")

    try:
        material = _already_appended(blend, name) or _append(blend, name)
    except Exception:
        logger.exception("[Generations] Could not read material '%s' from %s", name, blend)
        return False, rpt_("Could not apply '{name}'").format(name=name)
    if material is None:
        return False, rpt_("'{name}' is not in that file anymore").format(name=name)

    for obj in targets:
        assign_to_active_slot(obj, material)
    _redraw(target)
    if layered:
        return True, rpt_("Applied '{name}' to {count} object(s); skipped {skipped} "
                          "painted with Mixar Paint layers").format(
            name=name, count=len(targets), skipped=len(layered))
    return True, rpt_("Applied '{name}' to {count} object(s)").format(name=name, count=len(targets))

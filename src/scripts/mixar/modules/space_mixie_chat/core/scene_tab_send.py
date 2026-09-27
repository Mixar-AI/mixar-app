# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Send objects from one scene tab to another (parallel scene tabs).

The only cross-tab path: a send is a duplicate (object, data, materials),
never a link, and every reference the shallow ``Object.copy`` keeps to the
source tab — parent, constraint targets, modifier objects — is remapped
onto the copies or dropped, so nothing an agent does in one tab can reach
the copy. The operator lives in ``ui/operators/scene_tab_ops``.
"""

from __future__ import annotations

from mixar.config.logging_config import get_logger
from mixar.modules.common.scenes_log import slog

from ..constants import is_lane_scene

logger = get_logger(__name__)


def send_selection_to_scene(source, target, objects) -> list:
    """Copy ``objects`` (and their object data and materials, Shift-D
    semantics) from ``source`` into ``target``'s root collection. The only
    cross-tab path: tabs never share datablocks, so nothing an agent does in
    one tab can reach the copy. Returns the new objects' names.

    ``Object.copy`` is shallow: the parent, constraint targets and modifier
    objects still point at the originals. Every such reference is remapped
    onto the copy of its target when that was copied too, and dropped
    otherwise (the parent is dropped keeping the world transform) — a copy
    that still followed an object in the source tab would move with it.
    """
    if target is None or target is source or is_lane_scene(target):
        return []
    copies = {}
    for obj in objects:
        try:
            copy = obj.copy()
            if getattr(obj, "data", None) is not None:
                copy.data = obj.data.copy()
                slots = getattr(copy.data, "materials", None)
                if slots is not None:
                    for index, material in enumerate(list(slots)):
                        if material is not None:
                            slots[index] = material.copy()
            target.collection.objects.link(copy)
            copies[obj] = copy
        except Exception as error:  # noqa: BLE001
            logger.warning("send to scene skipped %s: %s", getattr(obj, "name", "?"), error)
    for obj, copy in copies.items():
        _remap_object_references(obj, copy, copies)
    made = [copy.name for copy in copies.values()]
    slog("tab.send", scene=source, target=target.name, count=len(made))
    return made


def _remap_object_references(original, copy, copies) -> None:
    """Point ``copy``'s parent, constraints and modifiers at copies, never at
    the source tab's objects (see ``send_selection_to_scene``)."""
    parent = getattr(copy, "parent", None)
    if parent is not None:
        if parent in copies:
            copy.parent = copies[parent]
        else:
            try:
                world = original.matrix_world.copy()
                copy.parent = None
                copy.matrix_world = world
            except Exception:  # noqa: BLE001 — a double without matrices
                copy.parent = None
    for holder in _object_pointer_holders(copy):
        for name in _object_pointer_props(holder):
            try:
                pointed = getattr(holder, name)
            except Exception:  # noqa: BLE001
                continue
            if pointed is None or pointed is copy:
                continue
            replacement = copies.get(pointed)
            if replacement is None and pointed in copies.values():
                continue
            try:
                setattr(holder, name, replacement)
            except Exception:  # noqa: BLE001 — a read-only pointer
                logger.debug("could not remap %s.%s", holder, name, exc_info=True)


def _object_pointer_holders(obj):
    for collection_name in ("constraints", "modifiers"):
        try:
            yield from list(getattr(obj, collection_name, None) or [])
        except Exception:  # noqa: BLE001
            continue


def _object_pointer_props(holder) -> list:
    """The RNA pointer properties of a constraint / modifier that hold an
    Object (``target``, ``object``, ``mirror_object``, ``pole_target``…)."""
    names = []
    try:
        for prop in holder.bl_rna.properties:
            if prop.type != 'POINTER' or prop.is_readonly:
                continue
            fixed = getattr(prop, "fixed_type", None)
            if fixed is not None and getattr(fixed, "identifier", "") == "Object":
                names.append(prop.identifier)
    except Exception:  # noqa: BLE001 — a double without RNA
        for name in ("target", "object", "pole_target", "mirror_object",
                     "offset_object", "origin", "curve", "object_from", "object_to"):
            if hasattr(holder, name):
                names.append(name)
    return names

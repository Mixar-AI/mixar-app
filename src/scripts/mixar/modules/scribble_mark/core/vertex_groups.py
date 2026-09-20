# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turning a mark into a named selection on the mesh.

This is the handoff that makes the difference between the agent knowing
roughly where the user pointed and being able to edit exactly that. Passing
coordinates makes the agent write projection maths inside a sandbox script;
passing ``mixar_mark_0001`` gives it a **noun it can address** —

    obj.vertex_groups.active = obj.vertex_groups["mixar_mark_0001"]

— with no re-derivation and no drift.

Two deliberate limits, both documented to the agent rather than hidden:

* the selection is **screen-space and front-facing** — the vertices you can
  see inside the loop. That is what "I circled this wall" means; including
  the far wall because it happens to project inside the same outline is not.
* it is built from the object's **original** vertices. Vertex groups are
  indexed by base vertex, so anything measured on evaluated geometry could
  not be written back. On a mesh whose visible shape comes from generative
  modifiers, the base cage may sit elsewhere; the group is still written
  against what the group system can actually address.
"""

from __future__ import annotations

from mixar.config.logging_config import get_logger

from .coverage import points_in_polygon_mask
from .projection import project_mesh_vertices
from ..constants import (
    MARK_SERIAL_DIGITS,
    MARK_VERTEX_GROUP_PREFIX,
    MAX_MESH_VERTICES_FOR_GROUP,
    MIN_MARKED_VERTICES,
)

logger = get_logger(__name__)


def group_name(serial):
    """``mixar_mark_0001`` — stable, so a later turn can still address it."""
    return f"{MARK_VERTEX_GROUP_PREFIX}{int(serial):0{MARK_SERIAL_DIGITS}d}"


def marked_vertex_indices(region, rv3d, obj, polygon_px):
    """Original-mesh vertex indices the mark encloses, or None.

    None (rather than an empty list) means the pass could not run — no mesh,
    no numpy, too many vertices, a degenerate outline. Callers report that as
    "no sub-object selection" instead of "the user selected nothing".
    """
    if getattr(obj, "type", None) != "MESH":
        return None
    if len(polygon_px) < 3:
        return None

    mesh = getattr(obj, "data", None)
    vertices = getattr(mesh, "vertices", None)
    count = len(vertices) if vertices is not None else 0
    if not count:
        return None
    if count > MAX_MESH_VERTICES_FOR_GROUP:
        logger.info(
            "Scribble mark: skipping vertex group for %s (%d vertices > %d)",
            obj.name, count, MAX_MESH_VERTICES_FOR_GROUP,
        )
        return None

    xs, ys, usable = project_mesh_vertices(region, rv3d, obj)
    if xs is None:
        return None

    inside = points_in_polygon_mask(xs, ys, polygon_px)
    if inside is None:
        return None

    try:
        import numpy as np
        selected = np.nonzero(inside & usable)[0]
        return [int(i) for i in selected]
    except Exception as exc:  # noqa: BLE001 — never fail a send over a group
        logger.debug("Scribble mark: vertex selection failed on %s: %s",
                     obj.name, exc)
        return None


def write_group(obj, name, indices):
    """Create (or replace) a vertex group holding *indices*. Returns its name.

    Returns None without writing anything when the selection is too sparse to
    be worth addressing, or when the object is in a mode that forbids the
    write. Replacing rather than merging matters: re-marking the same object
    must not accumulate the union of every region ever circled.
    """
    if not indices or len(indices) < MIN_MARKED_VERTICES:
        return None
    if getattr(obj, "type", None) != "MESH":
        return None

    # vertex_groups.add() is invalid while the mesh is open in edit mode —
    # the edit-mesh owns the data and the write is silently lost or raises.
    if getattr(obj, "mode", "OBJECT") != "OBJECT":
        logger.info(
            "Scribble mark: not writing %s on %s — object is in %s mode",
            name, obj.name, obj.mode,
        )
        return None

    try:
        existing = obj.vertex_groups.get(name)
        if existing is not None:
            obj.vertex_groups.remove(existing)
        group = obj.vertex_groups.new(name=name)
        group.add(list(indices), 1.0, "REPLACE")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scribble mark: could not write vertex group %s on %s: %s",
                       name, obj.name, exc)
        return None

    # Blender uniquifies a colliding name, so report what actually exists.
    return group.name


def remove_group(obj, name):
    """Best-effort removal of a mark's group. Never raises."""
    try:
        existing = obj.vertex_groups.get(name)
        if existing is not None:
            obj.vertex_groups.remove(existing)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: could not remove vertex group %s: %s",
                     name, exc)

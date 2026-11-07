# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Repair invalid Mesh topology an agent script leaves behind, before anything draws it.

The Mesh data API lets a script write face offsets and corner / edge vertex
indices directly (``vertices.add`` + ``loops.add`` + ``foreach_set``, raw
``loop_start`` / ``vertex_index``, ``polygons.add``). Blender does not check them
on write. An out-of-range or uninitialised index is only read later, natively,
by whatever touches the mesh next: the vertex-to-face map
(``offset_indices::build_reverse_offsets`` / ``array_utils::count_indices``),
custom normals (``mesh_normals_corner_custom_set``), triangulation for drawing
(``calc_face_tri_starts_mesh``) or a render worker loading the snapshot. Each of
those is a native crash that Python cannot catch (prod 4.3.6/4.4.0, macOS and
Windows). At our Blender pin, ``loops/edges/polygons.add(n)`` on an existing mesh
also left the new elements uninitialised (``editors/mesh/mesh_data.cc`` backport).

``snapshot_mesh_sizes`` records every mesh's element counts before a script runs.
``repair_changed_meshes`` runs after the script, whether it succeeded or raised.
It applies Blender's native validator to each mesh the script created or resized,
and returns the names of meshes the validator had to fix. Valid meshes are not
changed. Custom data is kept (``clean_customdata=False``). Meshes in Edit Mode
(their BMesh is authoritative; ``sandbox_editmesh`` refreshes it) and linked
library meshes are skipped. A script that rewrites indices without changing any
element count is not detected; validating every mesh after every script would
cost time proportional to the whole file.
"""

import logging
import time

import bpy

logger = logging.getLogger(__name__)

NOTE = (
    "Mixar repaired invalid mesh topology left by this script in {names}: some face, "
    "edge or corner indices were out of range or unset, which crashes Blender on the "
    "next redraw. Invalid elements were removed. Rebuild the geometry with in-range, "
    "distinct vertex indices (e.g. mesh.from_pydata on a new mesh), then check the result."
)

#: Log when validation takes longer than this many seconds (main-thread budget).
_SLOW_S = 0.05


def _sizes(mesh):
    return (len(mesh.vertices), len(mesh.edges), len(mesh.loops), len(mesh.polygons))


def snapshot_mesh_sizes():
    """Map ``as_pointer()`` to element counts for every mesh in the file."""
    sizes = {}
    for mesh in bpy.data.meshes:
        try:
            sizes[mesh.as_pointer()] = _sizes(mesh)
        except Exception:  # noqa: BLE001 - one unreadable mesh never blocks the rest
            continue
    return sizes


def repair_changed_meshes(before):
    """Validate the meshes created or resized since ``before``; return the names repaired.

    ``before`` is ``None`` when no snapshot was taken (the script never ran):
    nothing is validated then.
    """
    if before is None:
        return []
    repaired = []
    start = time.perf_counter()
    for mesh in bpy.data.meshes:
        try:
            if mesh.library is not None or mesh.is_editmode:
                continue
            sizes = _sizes(mesh)
            if before.get(mesh.as_pointer()) == sizes or not any(sizes):
                continue
            if mesh.validate(verbose=False, clean_customdata=False):
                repaired.append(mesh.name_full)
        except Exception:  # noqa: BLE001 - one bad mesh never blocks the others
            logger.exception("Validating mesh topology after an agent script failed")
    elapsed = time.perf_counter() - start
    if elapsed > _SLOW_S:
        logger.info("Post-script mesh validation took %.0f ms", elapsed * 1000)
    if repaired:
        logger.warning("Agent script left invalid topology in %s; repaired", repaired)
    return repaired

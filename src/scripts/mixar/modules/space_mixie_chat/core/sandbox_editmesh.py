# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Refresh every Edit Mode mesh after an agent script that used ``bmesh``.

``bmesh.from_edit_mesh(me)`` hands a script the live edit-mode BMesh. A script
that adds, deletes, splits or joins geometry through it and returns without
``bmesh.update_edit_mesh(me)`` leaves the mesh's cached loop triangles
(``BMEditMesh.looptris``) describing faces that no longer exist. The next
viewport redraw rebuilds the triangle index buffer from that cache
(``extract_tris_bmesh``) and reads freed loops: a native crash we cannot catch
(prod 4.4.0, Windows: ``extract_tris_bmesh`` <- ``extract_mesh_ibo_tris.cc:81``).

``refresh_edit_meshes`` runs right after such a script and does what the
script should have: ``update_edit_mesh`` with loop triangles recomputed, for
every mesh object in Edit Mode. Only ``bmesh`` reaches the edit BMesh from
Python, so a script that never names it skips the walk.
"""

import bmesh
import bpy


def may_edit_bmesh(script) -> bool:
    """Whether ``script`` could have changed an edit-mode BMesh. True when the
    source is unavailable: then the refresh runs."""
    if not isinstance(script, str) or not script:
        return True
    return "bmesh" in script


def refresh_edit_meshes() -> int:
    """Recompute loop triangles (and tag a redraw) for every mesh in Edit Mode;
    returns how many were refreshed. A mesh that cannot be refreshed is skipped."""
    refreshed = 0
    seen = set()
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or ob.mode != 'EDIT':
            continue
        mesh = ob.data
        if mesh is None or mesh.name_full in seen or not mesh.is_editmode:
            continue
        seen.add(mesh.name_full)
        try:
            bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=True)
            refreshed += 1
        except Exception:  # noqa: BLE001 - one bad mesh never blocks the others
            continue
    return refreshed

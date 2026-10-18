# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export-time material swap shared by ``export_scene`` and ``export_asset``.

A Mixar paint slot is a node-group material that no exporter can read.
While an export runs, every slot whose active output reaches a Mixar group
is swapped to the Principled/image material that
``paint/core/asset_export/bake_and_assign.create_export_material`` builds from
the stack's BAKED channel images. The swap is undone and the temporary
materials are freed on exit.

Only a stack with at least one BAKED channel image is swapped. The swap
material holds baked images alone, so for an unbaked stack it was an
untextured Principled and the file lost every texture the exporter still
reaches through the original node tree (glTF follows a layer's image node
into the group): a game GLB of an unbaked boss shipped with no images. An
unbaked stack exports its own material; baking is ``repair_export``'s job.
"""

from contextlib import contextmanager

import bpy

from .export_preflight import active_mixar_nodes


def has_baked_channels(tree) -> bool:
    """True when a channel of the stack in ``tree`` has a baked image."""
    mp = getattr(tree, "mp", None)
    nodes = getattr(tree, "nodes", None)
    if mp is None or nodes is None:
        return False
    for channel in getattr(mp, "channels", ()) or ():
        baked = getattr(channel, "baked", "")
        node = nodes.get(baked) if baked else None
        if node is not None and getattr(node, "image", None) is not None:
            return True
    return False


@contextmanager
def temporary_export_materials(meshes):
    """Swap every Mixar slot to a Principled/image material for export."""
    from mixar.modules.paint.core.asset_export.bake_and_assign import (
        create_export_material,
    )

    assignments, created = [], []
    try:
        for obj in meshes:
            original_index = obj.active_material_index
            try:
                for index, material in enumerate(list(obj.data.materials)):
                    nodes = active_mixar_nodes(material)
                    if not nodes or not has_baked_channels(nodes[0].node_tree):
                        continue
                    obj.active_material_index = index
                    export_material = create_export_material(
                        obj, nodes[0].node_tree.mp, nodes[0].node_tree,
                    )
                    if export_material:
                        assignments.append((obj, index, material))
                        created.append(export_material)
            finally:
                obj.active_material_index = original_index
        yield
    finally:
        for obj, index, material in reversed(assignments):
            try:
                obj.data.materials[index] = material
            except Exception:
                pass
        for material in created:
            try:
                if material.users == 0:
                    bpy.data.materials.remove(material)
            except Exception:
                pass

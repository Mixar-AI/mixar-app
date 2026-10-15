# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export-time material swap shared by ``export_scene`` and ``export_asset``.

A Mixar paint slot is a node-group material that no exporter can read.
While an export runs, every slot whose active output reaches a Mixar group
is swapped to the Principled/image material that
``paint/core/asset_export/bake_and_assign.create_export_material`` builds from
the stack's BAKED channel images. The swap is undone and the temporary
materials are freed on exit. This only swaps: an unbaked stack still exports
without textures (baking is ``repair_export``'s job).
"""

from contextlib import contextmanager

import bpy

from .export_preflight import active_mixar_nodes


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
                    if not nodes:
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

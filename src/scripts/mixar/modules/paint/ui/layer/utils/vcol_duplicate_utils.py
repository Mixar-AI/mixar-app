# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vertex color duplication utilities for layer duplication."""

from ....core.element.create_vcol import new_vertex_color
from ....core.element.update_vcol import copy_vertex_color_data
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.node_utils import get_vertex_colors
from ....utils.blender_commons import get_active_material, get_unique_name


def duplicate_vertex_colors(
    mp, vcol_names, vcol_nodes, vcol_users, vcol_user_types, duplicate_blank=False
):
    """Duplicate vertex colors for layers and masks.

    Args:
        mp: Material properties object.
        vcol_names (list): List of vertex color names to duplicate.
        vcol_nodes (list): List of nodes using vertex colors.
        vcol_users (list): List of layer/mask users of vertex colors.
        vcol_user_types (list): List of user types ('LAYER', 'CHANNEL', 'MASK').
        duplicate_blank (bool, optional): Create blank duplicates. Defaults to False.
    """
    objs = get_all_objects_with_same_materials(get_active_material())

    for i, vcol_name in enumerate(vcol_names):
        # Get all available vcol names across all objects
        all_vcol_names = []
        for obj in objs:
            vcols = get_vertex_colors(obj)
            for vcol in vcols:
                if vcol.name not in all_vcol_names:
                    all_vcol_names.append(vcol.name)

        # Get new name based on already available vcol names
        new_vcol_name = get_unique_name(vcol_name, all_vcol_names)

        # Duplicate vertex color
        for obj in objs:
            vcols = get_vertex_colors(obj)
            if vcol_name in vcols:
                vcol = vcols.get(vcol_name)

                if vcol_user_types[i] == "LAYER":
                    color = (0.0, 0.0, 0.0, 0.0)
                else:
                    color = (0.0, 0.0, 0.0, 1.0)

                new_vcol = new_vertex_color(
                    obj, new_vcol_name, vcol.data_type, vcol.domain, color_fill=color
                )

                if not duplicate_blank:
                    copy_vertex_color_data(obj, vcol_name, new_vcol_name)

        # Set new vertex color to node and user
        vcol_nodes[i].attribute_name = new_vcol_name
        mp.halt_update = True
        vcol_users[i].name = new_vcol_name
        mp.halt_update = False

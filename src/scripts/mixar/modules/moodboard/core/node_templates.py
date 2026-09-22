# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Editable node starters; the catalog continues to own models and settings."""

from ..constants import NODE_TEMPLATES
from .capabilities import capability_available


def template_available(template_id):
    template = next((item for item in NODE_TEMPLATES if item[0] == template_id), None)
    return template is not None and (
        template[3] is None or capability_available(template[3], action_type=template_id)
    )


def available_templates():
    """Current Add-menu entries; never cache catalog-dependent visibility."""
    return tuple(item for item in NODE_TEMPLATES if template_available(item[0]))


def create_template(scene, template_id, center, *, exact_position=False):
    """Create a draft at a drop point, or find free space for a click."""
    if not template_available(template_id):
        raise ValueError("This template needs an available generation model. Check your connection.")

    from .asset_nodes import create_empty_mesh_node, find_free_asset_position
    from .node_graph import create_connected_action

    node = (create_empty_mesh_node(scene, center=center) if template_id == 'MESH_REFERENCE'
            else create_connected_action(scene, template_id, allow_empty=True, drop_position=center))
    if exact_position:
        node.position_x = center[0] - node.width * .5
        node.position_y = center[1] - node.height * .5
    else:
        node.position_x, node.position_y = find_free_asset_position(
            scene, *center, node.width, node.height, exclude=node,
        )
    return node

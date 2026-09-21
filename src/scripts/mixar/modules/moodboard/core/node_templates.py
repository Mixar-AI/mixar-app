# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Editable node starters; the catalog continues to own models and settings."""

from ..constants import NODE_TEMPLATES
from .capabilities import capability_available


def template_available(template_id):
    template = next((item for item in NODE_TEMPLATES if item[0] == template_id), None)
    return template is not None and capability_available(template[3])


def create_template(scene, template_id, center):
    """Create a draft near the view, reusing graph wiring and placement rules."""
    if not template_available(template_id):
        raise ValueError("This template needs an available generation model. Check your connection.")

    from .asset_nodes import find_free_asset_position
    from .node_graph import create_connected_action

    node = create_connected_action(scene, template_id, allow_empty=True, drop_position=center)
    node.position_x, node.position_y = find_free_asset_position(
        scene, *center, node.width, node.height, exclude=node,
    )
    return node

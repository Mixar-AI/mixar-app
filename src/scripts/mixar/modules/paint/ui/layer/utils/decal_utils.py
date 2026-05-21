# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Decal empty duplication utilities for layer duplication."""

import bpy

from ....core.node.node_utils import create_decal_empty
from ....utils.blender_commons import get_unique_name, link_object
from .driver_utils import update_driver_targets


def duplicate_decal_empty_reference(
    texcoord_name, ttree, set_new_decal_position, duplicated_empties
):
    """Duplicate decal empty object reference for layer duplication.

    Args:
        texcoord_name (str): Name of texture coordinate node.
        ttree: Node tree containing the texture coordinate.
        set_new_decal_position (bool): Whether to set new position for duplicated decal.
        duplicated_empties (dict): Dictionary tracking duplicated empty objects.
    """
    texcoord = ttree.nodes.get(texcoord_name)
    if not texcoord or not hasattr(texcoord, "object") or not texcoord.object:
        return

    original_empty = texcoord.object

    if set_new_decal_position:
        texcoord.object = create_decal_empty()
    else:
        if original_empty in duplicated_empties:
            new_empty = duplicated_empties[original_empty]
        else:
            nname = get_unique_name(original_empty.name, bpy.data.objects)
            custom_collection = (
                original_empty.users_collection[0]
                if len(original_empty.users_collection) > 0
                else None
            )
            new_empty = original_empty.copy()
            new_empty.name = nname
            link_object(bpy.context.scene, new_empty, custom_collection)

            duplicated_empties[original_empty] = new_empty

            # Update drivers on the new empty to point to any other duplicated empties
            update_driver_targets(new_empty, duplicated_empties)

        texcoord.object = new_empty

# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Validation functions for baking operations"""

from mixar.config.logging_config import get_logger

from ....core.layer.layer_utils import get_uv_layers
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.get_nodes import get_material_output

logger = get_logger(__name__)

# Constants for validation
BAKE_PROBLEMATIC_MODIFIERS = {
    "MIRROR",
    "SOLIDIFY",
    "ARRAY",
}

JOIN_PROBLEMATIC_TEXCOORDS = {
    "Object",
    "Generated",
}


def get_problematic_modifiers(obj):
    """Get list of modifiers that may cause problems during baking.

    Args:
        obj: Blender object to check for problematic modifiers.

    Returns:
        list: List of modifier objects that are problematic for baking.
    """
    pms = []

    for m in obj.modifiers:
        if m.type in BAKE_PROBLEMATIC_MODIFIERS:
            # Mirror modifier is not problematic if mirror uv is used
            if m.type == "MIRROR":
                if not m.use_mirror_u and not m.use_mirror_v:
                    if m.offset_u == 0.0 and m.offset_v == 0.0:
                        pms.append(m)
            else:
                pms.append(m)

    return pms


def search_join_problematic_texcoord(tree, node):
    """Search for texcoord nodes that output join problematic texcoords outside mp.

    Args:
        tree: Node tree to search.
        node: Starting node to search from.

    Returns:
        bool: True if problematic texcoord is found, False otherwise.
    """
    for inp in node.inputs:
        for link in inp.links:
            from_node = link.from_node
            from_socket = link.from_socket
            if (
                from_node.type == "TEX_COORD"
                and from_socket.name in JOIN_PROBLEMATIC_TEXCOORDS
            ):
                return True
            elif (
                node.type == "GROUP"
                and node.node_tree
                and not node.node_tree.mp.is_mpaint_node
            ):
                output = [
                    n
                    for n in node.node_tree.nodes
                    if n.type == "GROUP_OUTPUT" and n.is_active_output
                ]
                if output:
                    if search_join_problematic_texcoord(node.node_tree, output[0]):
                        return True
            if search_join_problematic_texcoord(tree, from_node):
                return True

    return False


def is_there_any_missmatched_attribute_types(objs):
    """Check if there are any mismatched attribute types across objects.

    Args:
        objs (list): List of Blender objects to check.

    Returns:
        bool: True if mismatched attribute types are found, False otherwise.
    """
    # Get number of attributes founds
    attr_counts = {}
    for obj in objs:
        for attr in obj.data.attributes:
            if attr.name not in attr_counts:
                attr_counts[attr.name] = 1
            else:
                attr_counts[attr.name] += 1

    # Get the same attribute used in all objects
    same_attrs = []
    for name, count in attr_counts.items():
        if count == len(objs):
            same_attrs.append(name)

    # Is there any missmatched type data
    for name in same_attrs:
        data_type = ""
        domain = ""
        for obj in objs:
            attr = obj.data.attributes[name]

            if data_type == "":
                data_type = attr.data_type
            elif data_type != attr.data_type:
                return True

            if domain == "":
                domain = attr.domain
            elif domain != attr.domain:
                return True

    return False


def is_join_objects_problematic(mp, mat=None):
    """Check if joining objects is problematic for baking.

    Args:
        mp: MPaint node tree property group.
        mat: Blender material object, defaults to None.

    Returns:
        bool: True if joining objects would be problematic, False otherwise.
    """
    for layer in mp.layers:

        for mask in layer.masks:
            if mask.type in {"VCOL", "HEMI", "COLOR_ID"}:
                continue
            if mask.texcoord_type in JOIN_PROBLEMATIC_TEXCOORDS or mask.type in {
                "OBJECT_INDEX"
            }:
                logger.info(
                    "Merged bake is not happening because there's object index mask"
                )
                return True

        if layer.type in {"VCOL", "COLOR", "BACKGROUND", "HEMI", "GROUP"}:
            continue
        if layer.texcoord_type in JOIN_PROBLEMATIC_TEXCOORDS:
            logger.info(
                "Merged bake is not happening because there's problematic texcoord used"
            )
            return True

    if mat:
        output = get_material_output(mat)
        if output:
            if search_join_problematic_texcoord(mat.node_tree, output):
                logger.info(
                    "Merged bake is not happening because there's problematic texcoord used outside node"
                )
                return True

        # Check for missmatched color attribute data
        objs = get_all_objects_with_same_materials(mat, True)
        if is_there_any_missmatched_attribute_types(objs):
            logger.info(
                "Merged bake is not happening because there's missmatched attribute data types"
            )
            return True

    return False


def is_object_bakeable(obj):
    """Check if an object can be used for baking.

    Args:
        obj: Blender object to check.

    Returns:
        bool: True if object is bakeable, False otherwise.
    """
    if obj.type != "MESH":
        return False
    if hasattr(obj, "hide_viewport") and obj.hide_viewport:
        return False
    if len(get_uv_layers(obj)) == 0:
        return False
    if len(obj.data.polygons) == 0:
        return False

    return True

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask source setup functions for configuring mask source nodes.

This module contains functions for setting up various types of mask sources
including color ID, object index, edge detection, and modifier-based sources.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.lib.lib import (
    COLOR_ID_EQUAL_282,
    EDGE_DETECT,
    EDGE_DETECT_CUSTOM_NORMAL,
    HEMI,
    OBJECT_INDEX_EQUAL,
)
from ...core.node.create_nodes import new_node
from ...core.node.node_utils import get_node_tree_lib, remove_node
from ...utils.blender_commons import (
    enable_eevee_ao,
    get_bpy_data,
    remove_datablock,
)


def setup_color_id_source(mask, source, color_id=None):
    """Configure a color ID mask source node with specified color values.

    Args:
        mask: YLayerMask property group to configure.
        source: Shader node to set up as color ID source.
        color_id (tuple, optional): RGB color tuple (3 floats). Defaults to None, using mask.color_id.
    """
    loaded_tree = get_node_tree_lib(COLOR_ID_EQUAL_282)
    if not loaded_tree:
        logger.error(f"Failed to load color ID library: {COLOR_ID_EQUAL_282}")
        return

    source.node_tree = loaded_tree

    if color_id is not None:
        mask.color_id = color_id
    else:
        color_id = mask.color_id

    col = (color_id[0], color_id[1], color_id[2], 1.0)

    # Safety check for inputs
    if len(source.inputs) > 0:
        source.inputs[0].default_value = col
    else:
        logger.error(f"Color ID source has no inputs. Node tree: {source.node_tree.name if source.node_tree else 'None'}")


def setup_object_idx_source(mask, source, object_index=None):
    """Configure an object index mask source node with specified index value.

    Args:
        mask: YLayerMask property group to configure.
        source: Shader node to set up as object index source.
        object_index (int, optional): Object pass index value. Defaults to None, using mask.object_index.
    """
    loaded_tree = get_node_tree_lib(OBJECT_INDEX_EQUAL)
    if not loaded_tree:
        logger.error(f"Failed to load object index library: {OBJECT_INDEX_EQUAL}")
        return

    source.node_tree = loaded_tree

    if object_index is not None:
        mask.object_index = object_index
    else:
        object_index = mask.object_index

    # Safety check for inputs
    if len(source.inputs) > 0:
        source.inputs[0].default_value = object_index
    else:
        logger.error(f"Object index source has no inputs. Node tree: {source.node_tree.name if source.node_tree else 'None'}")


def setup_edge_detect_source(entity, source, edge_detect_radius=None):
    """Configure an edge detection mask source node with detection radius.

    Args:
        entity: YLayerMask property group to configure.
        source: Shader node to set up as edge detection source.
        edge_detect_radius (float, optional): Detection radius value. Defaults to None, using entity.edge_detect_radius.

    Returns:
        bool: True if setup was successful, False otherwise.
    """
    if not source:
        logger.error("Edge detect source node is None")
        return False

    if entity.hemi_use_prev_normal:
        lib_name = EDGE_DETECT_CUSTOM_NORMAL
    else:
        lib_name = EDGE_DETECT

    ori_lib = source.node_tree
    if not ori_lib or ori_lib.name != lib_name:
        loaded_tree = get_node_tree_lib(lib_name)
        if loaded_tree:
            source.node_tree = loaded_tree
            logger.debug(f"Loaded edge detect library: {lib_name}, inputs: {len(source.inputs)}")
        else:
            logger.error(f"Failed to load edge detect library: {lib_name}. "
                        f"The mask may not function correctly.")
            return False

        if ori_lib and ori_lib.users == 0:
            remove_datablock(get_bpy_data().node_groups, ori_lib)

    # Safety check: ensure node_tree was loaded and has inputs before accessing
    if source.node_tree and len(source.inputs) > 0:
        if edge_detect_radius is not None:
            source.inputs[0].default_value = entity.edge_detect_radius = edge_detect_radius
        else:
            source.inputs[0].default_value = entity.edge_detect_radius
    else:
        logger.error(f"Edge detect source has no inputs. Node tree: {source.node_tree.name if source.node_tree else 'None'}, Inputs: {len(source.inputs)}")
        return False

    enable_eevee_ao()
    return True


def setup_modifier_mask_source(tree, mask, modifier_type):
    """Create and configure a modifier mask source node based on modifier type.

    Args:
        tree: Shader node tree to add the node to.
        mask: YLayerMask property group to configure.
        modifier_type (str): Type of modifier ('INVERT', 'RAMP', or 'CURVE').

    Returns:
        Created shader node for the modifier source, or None if modifier_type is invalid.
    """
    source = None
    if modifier_type == 'INVERT':
        source = new_node(tree, mask, 'source', 'ShaderNodeInvert', 'Mask Source')
    elif modifier_type == 'RAMP':
        source = new_node(tree, mask, 'source', 'ShaderNodeValToRGB', 'Mask Source')
    elif modifier_type == 'CURVE':
        source = new_node(tree, mask, 'source', 'ShaderNodeRGBCurve', 'Mask Source')

    return source

# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer source setup helper functions."""

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.layer.mappings import is_mapping_possible
from ....core.lib.lib import HEMI
from ....core.lib.lib_operations import duplicate_lib_node_tree
from ....core.node.create_nodes import new_node
from ....core.node.node_utils import get_node_tree_lib
from ....procedural_materials.material_registry import get_node_group
from ....utils.blender_commons import enable_eevee_ao
from ....utils.common import get_vcol_bl_idname, load_hemi_props, set_source_vcol_name
from ....utils.constants import layer_node_bl_idnames, TREE_START
from ...mask.mask_operators_helper import setup_edge_detect_source


def setup_layer_source(
    tree,
    layer,
    layer_type,
    image=None,
    vcol=None,
    solid_color=(1, 1, 1),
    hemi_space="WORLD",
    hemi_use_prev_normal=True,
    interpolation="Linear",
    edge_detect_radius=0.05,
    ao_distance=1.0,
    mp=None,
):
    """Set up the source node for a layer based on its type.

    Args:
        tree: The node tree for the layer.
        layer: The layer object.
        layer_type (str): Type of layer (IMAGE, VCOL, COLOR, HEMI, etc.).
        image: Blender image datablock for IMAGE layers. Defaults to None.
        vcol: Vertex color data for VCOL layers. Defaults to None.
        solid_color (tuple, optional): RGB color for solid color layers. Defaults to (1, 1, 1).
        hemi_space (str, optional): Space for hemisphere lighting. Defaults to "WORLD".
        hemi_use_prev_normal (bool, optional): Use previous normal for hemi. Defaults to True.
        interpolation (str, optional): Image interpolation type. Defaults to "Linear".
        edge_detect_radius (float, optional): Edge detection radius. Defaults to 0.05.
        ao_distance (float, optional): Ambient occlusion distance. Defaults to 1.0.
        mp: The mixar paint data structure. Defaults to None.

    Returns:
        The created source node, or None if creation failed.

    Raises:
        RuntimeError: If procedural material node group is not found.
    """
    # GROUP layers use the Start node (NodeGroupInput) as their source
    # because that's where the _Group inputs are available as outputs
    if layer.type == "GROUP":
        # Set layer.source to point to the Start node instead of creating a new node
        layer.source = TREE_START
        return tree.nodes.get(TREE_START)

    # Create source node based on layer type
    if layer.type == "VCOL":
        source = new_node(tree, layer, "source", get_vcol_bl_idname(), "Source")
    elif layer.type == "PROCEDURAL":
        source = new_node(tree, layer, "source", "ShaderNodeGroup", "Source")
    else:
        source = new_node(
            tree, layer, "source", layer_node_bl_idnames[layer.type], "Source"
        )

    # Configure source based on layer type
    if layer.type == "IMAGE":
        _setup_image_source(source, image, interpolation)
    elif layer.type == "VCOL":
        _setup_vcol_source(source, layer, vcol)
    elif layer.type == "COLOR":
        _setup_color_source(source, solid_color)
    elif layer.type == "HEMI":
        _setup_hemi_source(source, layer, hemi_space, hemi_use_prev_normal)
    elif layer.type == "EDGE_DETECT":
        _setup_edge_detect_source(source, layer, hemi_use_prev_normal, edge_detect_radius)
    elif layer.type == "AO":
        _setup_ao_source(layer, hemi_use_prev_normal, ao_distance)
    elif layer.type == "PROCEDURAL":
        _setup_procedural_source(source, layer, mp)

    return source


def _setup_image_source(source, image, interpolation):
    """Configure an image source node.

    Args:
        source: The source node.
        image: Blender image datablock.
        interpolation (str): Image interpolation type.
    """
    source.image = image
    source.interpolation = interpolation


def _setup_vcol_source(source, layer, vcol):
    """Configure a vertex color source node.

    Args:
        source: The source node.
        layer: The layer object.
        vcol: Vertex color data.
    """
    if vcol:
        set_source_vcol_name(source, vcol.name)
    else:
        set_source_vcol_name(source, layer.name)


def _setup_color_source(source, solid_color):
    """Configure a solid color source node.

    Args:
        source: The source node.
        solid_color (tuple): RGB color values.
    """
    col = (solid_color[0], solid_color[1], solid_color[2], 1.0)
    source.outputs[0].default_value = col


def _setup_hemi_source(source, layer, hemi_space, hemi_use_prev_normal):
    """Configure a hemisphere lighting source node.

    Args:
        source: The source node.
        layer: The layer object.
        hemi_space (str): Space for hemisphere lighting.
        hemi_use_prev_normal (bool): Use previous normal for hemi.
    """
    source.node_tree = get_node_tree_lib(HEMI)
    duplicate_lib_node_tree(source)

    load_hemi_props(layer, source)
    layer.hemi_space = hemi_space
    layer.hemi_use_prev_normal = hemi_use_prev_normal


def _setup_edge_detect_source(source, layer, hemi_use_prev_normal, edge_detect_radius):
    """Configure an edge detection source node.

    Args:
        source: The source node.
        layer: The layer object.
        hemi_use_prev_normal (bool): Use previous normal.
        edge_detect_radius (float): Edge detection radius.
    """
    layer.hemi_use_prev_normal = hemi_use_prev_normal
    setup_edge_detect_source(layer, source, edge_detect_radius)


def _setup_ao_source(layer, hemi_use_prev_normal, ao_distance):
    """Configure an ambient occlusion source.

    Args:
        layer: The layer object.
        hemi_use_prev_normal (bool): Use previous normal.
        ao_distance (float): Ambient occlusion distance.
    """
    layer.hemi_use_prev_normal = hemi_use_prev_normal
    layer.ao_distance = ao_distance
    enable_eevee_ao()


def _setup_procedural_source(source, layer, mp):
    """Configure a procedural material source node.

    Args:
        source: The source node.
        layer: The layer object.
        mp: The mixar paint data structure.

    Raises:
        RuntimeError: If the procedural material node group is not found.
    """
    material_id = layer.procedural_material_id
    node_group = get_node_group(material_id)
    if node_group:
        source.node_tree = node_group
        duplicate_lib_node_tree(source)
    else:
        error_msg = f"Failed to load procedural material: {material_id}. Node group not found."
        logger.error(error_msg)
        raise RuntimeError(error_msg)


def setup_mapping_node(tree, layer, mpup):
    """Set up a mapping node for the layer if applicable.

    Args:
        tree: The node tree for the layer.
        layer: The layer object.
        mpup: User preferences.

    Returns:
        The created mapping node, or None if not applicable.
    """
    from ....core.layer.check_layers import is_layer_using_vector

    if is_mapping_possible(layer.type, layer):
        mapping = new_node(tree, layer, "mapping", "ShaderNodeMapping", "Mapping")
        mapping.vector_type = "POINT"

        # Uniform Scale
        if is_layer_using_vector(layer):
            layer.enable_uniform_scale = mpup.enable_uniform_uv_scale_by_default

        return mapping
    return None

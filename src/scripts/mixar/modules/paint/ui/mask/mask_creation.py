# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask creation functions for adding new masks to layers.

This module contains the main function for creating new masks with various
types and configurations.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.check_processes import check_layer_bump_process
from ...core.element.get_elements import get_default_uv_name
from ...core.element.update_uv import refresh_temp_uv
from ...core.io.input_outputs.input_outputs_nodes import check_mask_image_linear_node
from ...core.layer.mappings import is_mapping_possible
from ...core.lib.lib import HEMI
from ...core.lib.lib_operations import duplicate_lib_node_tree
from ...core.node.check_nodes import (
    check_all_layer_channel_io_and_nodes,
    check_mask_mix_nodes,
    check_uv_nodes,
)
from ...core.node.create_nodes import new_node
from ...core.node.node_utils import get_node_tree_lib
from ...core.subtree.check_subtree import check_mask_source_tree
from ...core.subtree.get_subtree import get_tree
from ...utils.blender_commons import (
    enable_eevee_ao,
    get_active_object,
    get_unique_name,
    get_user_preferences,
)
from ...utils.common import (
    get_vcol_bl_idname,
    is_mask_using_vector,
    set_source_vcol_name,
)
from ...utils.constants import layer_node_bl_idnames
from ..image_atlas.image_atlas_utils import set_segment_mapping
from ..list_item.list_item_operators_helper import refresh_list_items
from .mask_utils import update_mask_texcoord_type
from .mask_source_setup import (
    setup_color_id_source,
    setup_edge_detect_source,
    setup_modifier_mask_source,
    setup_object_idx_source,
)


def add_new_mask(
        layer, name, mask_type, texcoord_type, uv_name, image=None, vcol_name='', segment=None,
        object_index=0, blend_type='MULTIPLY', hemi_space='WORLD', hemi_use_prev_normal=False,
        color_id=(1, 0, 1), source_input='RGB', edge_detect_radius=0.05,
        modifier_type='INVERT', interpolation='Linear', ao_distance=1.0
    ):
    """Add a new mask to a layer with specified configuration.

    Args:
        layer: YLayer property group to add the mask to.
        name (str): Name for the new mask.
        mask_type (str): Type of mask (IMAGE, VCOL, HEMI, etc.).
        texcoord_type (str): Texture coordinate type (UV, Generated, Object, etc.).
        uv_name (str): Name of UV map to use for coordinates.
        image (bpy.types.Image, optional): Image data for IMAGE type masks. Defaults to None.
        vcol_name (str, optional): Vertex color name for VCOL type masks. Defaults to ''.
        segment: Image atlas segment data. Defaults to None.
        object_index (int, optional): Object pass index for OBJECT_INDEX masks. Defaults to 0.
        blend_type (str, optional): Mask blend mode. Defaults to 'MULTIPLY'.
        hemi_space (str, optional): Hemisphere space for HEMI masks. Defaults to 'WORLD'.
        hemi_use_prev_normal (bool, optional): Use previous normal for lighting. Defaults to False.
        color_id (tuple, optional): RGB color tuple for COLOR_ID masks. Defaults to (1, 0, 1).
        source_input (str, optional): Source channel to use (RGB or ALPHA). Defaults to 'RGB'.
        edge_detect_radius (float, optional): Radius for edge detection masks. Defaults to 0.05.
        modifier_type (str, optional): Modifier type for MODIFIER masks. Defaults to 'INVERT'.
        interpolation (str, optional): Image interpolation type. Defaults to 'Linear'.
        ao_distance (float, optional): Ambient occlusion distance for AO masks. Defaults to 1.0.

    Returns:
        YLayerMask: The newly created mask property group.
    """
    mp = layer.id_data.mp
    mp.halt_update = True
    mpup = get_user_preferences()

    tree = get_tree(layer)
    nodes = tree.nodes

    mask = layer.masks.add()
    mask.name = get_unique_name(name, layer.masks)
    mask.type = mask_type
    mask.texcoord_type = texcoord_type
    mask.source_input = source_input

    # Uniform Scale
    if is_mask_using_vector(mask):
        mask.enable_uniform_scale = mpup.enable_uniform_uv_scale_by_default

    if segment:
        mask.segment_name = segment.name

    source = None
    if mask_type == 'VCOL':
        source = new_node(tree, mask, 'source', get_vcol_bl_idname(), 'Mask Source')
    elif mask_type == 'MODIFIER':
        source = setup_modifier_mask_source(tree, mask, modifier_type)
        mask.modifier_type = modifier_type

    elif mask.type != 'BACKFACE':
        source = new_node(tree, mask, 'source', layer_node_bl_idnames[mask_type], 'Mask Source')

    if image:
        source.image = image
        if hasattr(source, 'color_space'):
            source.color_space = 'NONE'
        source.interpolation = interpolation
    elif mask_type == 'VCOL':
        if vcol_name != '':
            set_source_vcol_name(source, vcol_name)
        else:
            set_source_vcol_name(source, name)

    if mask_type == 'HEMI':
        source.node_tree = get_node_tree_lib(HEMI)
        duplicate_lib_node_tree(source)
        mask.hemi_space = hemi_space
        mask.hemi_use_prev_normal = hemi_use_prev_normal

    elif mask_type == 'OBJECT_INDEX':
        setup_object_idx_source(mask, source, object_index)

    elif mask_type == 'COLOR_ID':
        setup_color_id_source(mask, source, color_id)

    elif mask_type == 'EDGE_DETECT':
        mask.hemi_use_prev_normal = hemi_use_prev_normal
        setup_edge_detect_source(mask, source, edge_detect_radius)

    elif mask_type == 'AO':
        mask.hemi_use_prev_normal = hemi_use_prev_normal
        mask.ao_distance = ao_distance
        enable_eevee_ao()

    # Set default uv name if it's an empty string
    if uv_name == '':
        uv_name = get_default_uv_name()

    mask.uv_name = uv_name

    if is_mapping_possible(mask_type):
        mapping = new_node(tree, mask, 'mapping', 'ShaderNodeMapping', 'Mask Mapping')
        mapping.vector_type = 'POINT' if segment else 'TEXTURE'

        if segment:
            set_segment_mapping(mask, segment, image)
            refresh_temp_uv(get_active_object(), mask)

    for i, root_ch in enumerate(mp.channels):
        c = mask.channels.add()

    mask.blend_type = blend_type

    # Check mask multiplies
    check_mask_mix_nodes(layer, tree)

    # Check mask source tree
    check_mask_source_tree(layer)

    # Check the need of bump process
    check_layer_bump_process(layer, tree)

    # Check uv maps
    check_uv_nodes(mp)

    # Check layer io
    check_all_layer_channel_io_and_nodes(layer, tree)

    # Check mask linear
    check_mask_image_linear_node(mask)

    mp.halt_update = False

    # Update coords
    update_mask_texcoord_type(mask, None, False)

    # Update list items
    refresh_list_items(mp)

    return mask

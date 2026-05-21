# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer creation helper functions."""

import bpy

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.element.check_elements import check_uvmap_on_other_objects_with_same_mat
from ....core.element.get_elements import get_default_uv_name
from ....core.element.update_fcurves import remap_layer_fcurves
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes
from ....core.layer.check_channels import check_start_end_root_ch_nodes
from ....core.layer.layer_utils import get_layer_index, get_layer_index_by_name
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.check_nodes import check_all_layer_channel_io_and_nodes, check_uv_nodes
from ....core.node.create_nodes import create_essential_nodes, new_node
from ....core.node.node_utils import create_info_nodes, get_active_mpaint_node
from ....core.subtree.get_subtree import get_index_dict, get_parent_dict
from ....core.subtree.update_subtree import set_parent_dict_val
from ....procedural_materials.material_registry import is_custom_material
from ....utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_unique_name,
    get_user_preferences,
)
from ....utils.constants import LAYERGROUP_PREFIX
from ...list_item.list_item_operators_helper import refresh_list_items
from ...udim.udim_utils import is_uvmap_udim
from .layer_enum_helpers import DEFAULT_NEW_IMG_SUFFIX, DEFAULT_NEW_VCOL_SUFFIX

# Import helper modules
from ..channel.layer_channel_setup import setup_layer_channels
from ..utils.layer_mask_setup import setup_layer_mask
from ..utils.layer_source_setup import setup_layer_source, setup_mapping_node

# Re-export for backward compatibility
from ....core.element.update_vcol import set_active_vertex_color

# Re-export helper functions for backward compatibility
from ..utils.layer_source_setup import (
    setup_layer_source,
    setup_mapping_node,
)
from ..utils.layer_mask_setup import (
    setup_layer_mask,
)
from ..channel.layer_channel_setup import (
    setup_layer_channels,
)


def add_new_layer(
    group_tree,
    layer_name,
    layer_type,
    channel_idx,
    blend_type,
    normal_blend_type,
    normal_map_type,
    texcoord_type,
    uv_name="",
    image=None,
    vcol=None,
    segment=None,
    solid_color=(1, 1, 1),
    add_mask=False,
    mask_type="IMAGE",
    mask_image_filepath="",
    mask_relative=True,
    mask_texcoord_type="UV",
    mask_color="BLACK",
    mask_use_hdr=False,
    mask_uv_name="",
    mask_width=1024,
    mask_height=1024,
    use_image_atlas_for_mask=False,
    hemi_space="WORLD",
    hemi_use_prev_normal=True,
    mask_color_id=(1, 0, 1),
    mask_vcol_fill=True,
    mask_vcol_data_type="BYTE_COLOR",
    mask_vcol_domain="CORNER",
    use_divider_alpha=False,
    use_udim_for_mask=False,
    interpolation="Linear",
    mask_interpolation="Linear",
    mask_edge_detect_radius=0.05,
    normal_space="TANGENT",
    edge_detect_radius=0.05,
    mask_use_prev_normal=True,
    ao_distance=1.0,
):
    """Create and configure a new paint layer with optional mask.

    Args:
        group_tree: Node tree group to add the layer to.
        layer_name (str): Name for the new layer.
        layer_type (str): Type of layer (IMAGE, VCOL, COLOR, HEMI, etc.).
        channel_idx (int): Index of channel to affect.
        blend_type (str): Blend mode for the layer.
        normal_blend_type (str): Blend mode for normal channel.
        normal_map_type (str): Type of normal map (BUMP_MAP, NORMAL_MAP, etc.).
        texcoord_type (str): Texture coordinate type (UV, Generated, etc.).
        uv_name (str, optional): Name of UV map to use. Defaults to "".
        image: Blender image datablock. Defaults to None.
        vcol: Vertex color data. Defaults to None.
        segment: Image atlas segment. Defaults to None.
        solid_color (tuple, optional): RGB color for solid color layers. Defaults to (1, 1, 1).
        add_mask (bool, optional): Whether to add a mask to the layer. Defaults to False.
        mask_type (str, optional): Type of mask (IMAGE, VCOL, etc.). Defaults to "IMAGE".
        mask_image_filepath (str, optional): Path to mask image file. Defaults to "".
        mask_relative (bool, optional): Use relative path for mask image. Defaults to True.
        mask_texcoord_type (str, optional): Texture coordinate type for mask. Defaults to "UV".
        mask_color (str, optional): Initial mask color (BLACK or WHITE). Defaults to "BLACK".
        mask_use_hdr (bool, optional): Use HDR for mask image. Defaults to False.
        mask_uv_name (str, optional): UV map name for mask. Defaults to "".
        mask_width (int, optional): Width of mask image in pixels. Defaults to 1024.
        mask_height (int, optional): Height of mask image in pixels. Defaults to 1024.
        use_image_atlas_for_mask (bool, optional): Use image atlas for mask. Defaults to False.
        hemi_space (str, optional): Space for hemisphere lighting. Defaults to "WORLD".
        hemi_use_prev_normal (bool, optional): Use previous normal for hemi. Defaults to True.
        mask_color_id (tuple, optional): Color ID for mask. Defaults to (1, 0, 1).
        mask_vcol_fill (bool, optional): Fill vertex color mask. Defaults to True.
        mask_vcol_data_type (str, optional): Vertex color data type. Defaults to "BYTE_COLOR".
        mask_vcol_domain (str, optional): Vertex color domain. Defaults to "CORNER".
        use_divider_alpha (bool, optional): Divide RGB by alpha. Defaults to False.
        use_udim_for_mask (bool, optional): Use UDIM tiles for mask. Defaults to False.
        interpolation (str, optional): Image interpolation type. Defaults to "Linear".
        mask_interpolation (str, optional): Mask interpolation type. Defaults to "Linear".
        mask_edge_detect_radius (float, optional): Edge detection radius for mask. Defaults to 0.05.
        normal_space (str, optional): Normal map space (TANGENT, OBJECT, etc.). Defaults to "TANGENT".
        edge_detect_radius (float, optional): Edge detection radius. Defaults to 0.05.
        mask_use_prev_normal (bool, optional): Use previous normal for mask. Defaults to True.
        ao_distance (float, optional): Ambient occlusion distance. Defaults to 1.0.

    Returns:
        YLayer: The newly created layer object.
    """
    # Delayed import to avoid circular dependency
    from ..callbacks.layer_state_callbacks import check_layer_projections

    mp = group_tree.mp
    mpup = get_user_preferences()
    obj = get_active_object()
    mat = get_active_material(obj)

    # Halt rearrangements and reconnections until all nodes already created
    mp.halt_reconnect = True

    # Initialize layer and get placement info
    layer, index = _initialize_layer(
        mp=mp,
        layer_name=layer_name,
        layer_type=layer_type,
        uv_name=uv_name,
        image=image,
        segment=segment,
        mat=mat,
    )

    # Create layer node tree and group node
    tree, group_node = _create_layer_node_tree(
        group_tree=group_tree,
        layer=layer,
        layer_name=layer_name,
    )

    # Set up source node
    try:
        setup_layer_source(
            tree=tree,
            layer=layer,
            layer_type=layer_type,
            image=image,
            vcol=vcol,
            solid_color=solid_color,
            hemi_space=hemi_space,
            hemi_use_prev_normal=hemi_use_prev_normal,
            interpolation=interpolation,
            edge_detect_radius=edge_detect_radius,
            ao_distance=ao_distance,
            mp=mp,
        )
    except RuntimeError:
        # Clean up the partially created layer on failure
        mp.layers.remove(index)
        raise

    # Set up mapping node
    setup_mapping_node(tree, layer, mpup)

    # Set layer coordinate type and spread fix
    layer.texcoord_type = texcoord_type
    layer.divide_rgb_by_alpha = use_divider_alpha

    # Add channels to current layer
    _add_layer_channels(layer, mp)

    # Add mask if requested
    if add_mask:
        setup_layer_mask(
            layer=layer,
            obj=obj,
            mat=mat,
            mp=mp,
            mask_type=mask_type,
            mask_image_filepath=mask_image_filepath,
            mask_relative=mask_relative,
            mask_texcoord_type=mask_texcoord_type,
            mask_color=mask_color,
            mask_use_hdr=mask_use_hdr,
            mask_uv_name=mask_uv_name,
            mask_width=mask_width,
            mask_height=mask_height,
            use_image_atlas_for_mask=use_image_atlas_for_mask,
            mask_color_id=mask_color_id,
            mask_vcol_fill=mask_vcol_fill,
            mask_vcol_data_type=mask_vcol_data_type,
            mask_vcol_domain=mask_vcol_domain,
            use_udim_for_mask=use_udim_for_mask,
            mask_interpolation=mask_interpolation,
            mask_edge_detect_radius=mask_edge_detect_radius,
            mask_use_prev_normal=mask_use_prev_normal,
        )

    # Set up layer channels
    setup_layer_channels(
        layer=layer,
        mp=mp,
        channel_idx=channel_idx,
        blend_type=blend_type,
        normal_blend_type=normal_blend_type,
        normal_map_type=normal_map_type,
        normal_space=normal_space,
        solid_color=solid_color,
    )

    # Finalize layer setup
    _finalize_layer(
        layer=layer,
        mp=mp,
        group_tree=group_tree,
        tree=tree,
        index=index,
        check_layer_projections=check_layer_projections,
    )

    return layer


def _initialize_layer(mp, layer_name, layer_type, uv_name, image, segment, mat):
    """Initialize a new layer with basic properties and placement.

    Args:
        mp: The mixar paint data structure.
        layer_name (str): Name for the new layer.
        layer_type (str): Type of layer.
        uv_name (str): Name of UV map to use.
        image: Blender image datablock.
        segment: Image atlas segment.
        mat: The active material.

    Returns:
        tuple: (layer, index) - The created layer and its index.
    """
    # Get parent and index dict
    parent_dict = get_parent_dict(mp)
    index_dict = get_index_dict(mp)

    # Get active layer
    try:
        active_layer = mp.layers[mp.active_layer_index]
    except:
        active_layer = None

    # GROUP layers should ALWAYS be at root level (never nested inside other groups)
    if layer_type == 'GROUP':
        parent_layer = None
        parent_idx = -1
        has_parent = False
        active_layer_is_group = active_layer.type == "GROUP" if active_layer else False
    else:
        # Get a possible parent layer group for non-GROUP layers
        parent_layer = None
        active_layer_is_group = False
        if active_layer:
            if active_layer.type == "GROUP":
                parent_layer = active_layer
                active_layer_is_group = True
            elif active_layer.parent_idx != -1:
                parent_layer = mp.layers[active_layer.parent_idx]

        # Get parent index
        if parent_layer:
            parent_idx = get_layer_index(parent_layer)
            has_parent = True
        else:
            parent_idx = -1
            has_parent = False

    # Add layer to group
    layer = mp.layers.add()

    # Check if this is a custom procedural material
    if is_custom_material(layer_type):
        layer.type = "PROCEDURAL"
        layer.procedural_material_id = layer_type
    else:
        layer.type = layer_type

    layer.name = get_unique_name(layer_name, mp.layers)

    # Set default uv name if it's an empty string
    if uv_name == "":
        uv_name = get_default_uv_name()

    layer.uv_name = uv_name
    check_uvmap_on_other_objects_with_same_mat(mat, uv_name)

    if segment:
        layer.segment_name = segment.name

    if image:
        layer.image_name = image.name

    # Move new layer to current index
    last_index = len(mp.layers) - 1
    if active_layer_is_group:
        index = mp.active_layer_index + 1
    else:
        index = mp.active_layer_index

    # Set parent index
    parent_dict = set_parent_dict_val(mp, parent_dict, layer.name, parent_idx)

    mp.layers.move(last_index, index)
    layer = mp.layers[index]  # Repoint to new index

    # Remap parents
    for lay in mp.layers:
        lay.parent_idx = get_layer_index_by_name(mp, parent_dict[lay.name])

    # Remap fcurves
    remap_layer_fcurves(mp, index_dict)

    return layer, index


def _create_layer_node_tree(group_tree, layer, layer_name):
    """Create the node tree and group node for a layer.

    Args:
        group_tree: The parent node tree group.
        layer: The layer object.
        layer_name (str): Name for the layer.

    Returns:
        tuple: (tree, group_node) - The created node tree and group node.
    """
    # New layer tree
    tree = bpy.data.node_groups.new(LAYERGROUP_PREFIX + layer_name, "ShaderNodeTree")
    tree.mp.is_mpaint_layer_node = True

    # New layer node group
    group_node = new_node(
        group_tree, layer, "group_node", "ShaderNodeGroup", layer_name
    )
    group_node.node_tree = tree

    # Create info nodes
    create_info_nodes(tree)

    # Tree start and end
    create_essential_nodes(tree, True, False, True)

    return tree, group_node


def _add_layer_channels(layer, mp):
    """Add channels to a layer.

    Args:
        layer: The layer object.
        mp: The mixar paint data structure.
    """
    for root_ch in mp.channels:
        ch = layer.channels.add()
        # Initialize channel with default values
        ch.enable = True
        ch.intensity_value = 1.0
        # Set default blend type based on channel type
        if root_ch.type == 'NORMAL':
            ch.normal_blend_type = 'MIX'
        else:
            ch.blend_type = 'MIX'
        # Set default override_type to LAYER (uses layer source)
        ch.override_type = 'LAYER'


def _finalize_layer(layer, mp, group_tree, tree, index, check_layer_projections):
    """Finalize layer setup with node connections and arrangements.

    Args:
        layer: The layer object.
        mp: The mixar paint data structure.
        group_tree: The parent node tree group.
        tree: The layer's node tree.
        index (int): The layer index.
        check_layer_projections: Function to check layer projections.
    """
    # Check uv maps
    check_uv_nodes(mp)

    # Check image projections
    check_layer_projections(layer)

    # Check and create layer channel nodes
    check_all_layer_channel_io_and_nodes(layer, tree)

    # Refresh paint image by updating the index
    mp.active_layer_index = index

    # Unhalt rearrangements and reconnections since all nodes already created
    mp.halt_reconnect = False

    # Check layer IO
    check_all_layer_channel_io_and_nodes(layer)
    check_start_end_root_ch_nodes(group_tree)

    # Rearrange node inside layers
    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    # Make sure new parent subitems is expanded
    if layer.parent_idx != -1:
        parent = mp.layers[layer.parent_idx]
        if not parent.expand_subitems:
            parent.expand_subitems = True

    # Update list items
    refresh_list_items(mp)


def update_new_layer_uv_map(self, context):
    """Update UV map settings and detect UDIM usage for new layer.

    Args:
        self: The property being updated.
        context: Blender context.
    """
    if hasattr(self, "type") and self.type != "IMAGE":
        self.use_udim = False
        return

    if get_user_preferences().enable_auto_udim_detection:
        mat = get_active_material()
        objs = get_all_objects_with_same_materials(mat)
        self.use_udim = is_uvmap_udim(objs, self.uv_map)


def update_new_layer_mask_uv_map(self, context):
    """Update mask UV map settings and detect UDIM usage.

    Args:
        self: The property being updated.
        context: Blender context.
    """
    if self.mask_type != "IMAGE":
        self.use_udim_for_mask = False
        return

    if get_user_preferences().enable_auto_udim_detection:
        mat = get_active_material()
        objs = get_all_objects_with_same_materials(mat)
        self.use_udim_for_mask = is_uvmap_udim(objs, self.mask_uv_name)


def update_channel_idx_new_layer(self, context):
    """Update layer interpolation settings based on selected channel.

    Args:
        self: The property being updated.
        context: Blender context.
    """
    node = get_active_mpaint_node()
    mp = node.node_tree.mp

    # Bump map will use cubic interpolation
    channel_idx = int(self.channel_idx)
    if channel_idx != -1 and channel_idx < len(mp.channels):
        channel = mp.channels[channel_idx]
    else:
        channel = None

    if channel and channel.type == "NORMAL" and self.normal_map_type == "BUMP_MAP":
        self.interpolation = "Cubic"

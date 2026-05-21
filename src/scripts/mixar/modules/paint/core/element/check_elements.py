# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ...utils.blender_commons import get_noncolor_name, get_scene_objects
from ...utils.constants import COLORID_TOLERANCE, COLOR_ID_VCOL_NAME, TEMP_UV
from ...utils.math_utils import isclose
from ..element.get_elements import (
    get_mask_color_id_color,
    get_uv_layers,
    get_vertex_colors,
)
from ..element.create_vcol import new_vertex_color
from ..element.update_vcol import set_active_vertex_color
from ..layer.check_layers import get_layer_enabled, is_layer_using_vector
from ..layer.get_channels import (
    get_layer_channel_gamma_value,
    get_layer_channel_normal_gamma_value,
    get_layer_gamma_value,
    get_layer_mask_gamma_value,
)
from ..layer.mappings import get_entity_mapping
from ..layer.transformations import get_transformation, is_transformed
from ..lib.lib import FLIP_Y
from ..node.create_nodes import check_new_node
from ..node.node_utils import get_node_tree_lib, remove_node
from ..subtree.get_subtree import (
    get_channel_source_tree,
    get_mask_tree,
    get_source_tree,
    get_tree,
)
from .....config.logging_config import get_logger
logger = get_logger(__name__)

def is_active_uv_map_missmatch_active_entity(obj, layer):
    """
    Check if the active UV map mismatches the active entity's UV map.

    Determines whether the currently active UV map on the object differs from
    the UV map required by the active entity (layer, mask, or channel).

    Parameters:
        obj: Blender mesh object to check UV maps on
        layer: Layer object containing entity information

    Returns:
        bool: True if UV map mismatch exists, False otherwise
    """
    mp = layer.id_data.mp

    entity = None

    for mask in layer.masks:
        if mask.active_edit:
            entity = mask
            entity_type = entity.type
            use_baked = entity.use_baked
            break

    for ch in layer.channels:
        if ch.active_edit:
            entity = layer
            entity_type = ch.override_type
            use_baked = False
            break

        if ch.active_edit_1:
            entity = layer
            entity_type = ch.override_1_type
            use_baked = False
            break

    if not entity:
        entity = layer
        entity_type = entity.type
        use_baked = entity.use_baked

    # Non image entity doesn't need matching UV
    if not use_baked and entity_type != 'IMAGE':
        return False

    # No need to check UV and transformation if entity is not using UV vector
    if (entity == layer and not is_layer_using_vector(entity)) or entity.texcoord_type != 'UV': return False

    # Get active UV 
    uv_layers = get_uv_layers(obj)
    if not uv_layers: return False
    uv_layer = uv_layers.active

    # Get active entity UV name
    uv_name = entity.uv_name if not use_baked or entity.baked_uv_name == '' else entity.baked_uv_name

    # Get mapping
    mapping = get_entity_mapping(entity, get_baked=use_baked)

    # Check mapping transformation
    if mapping and is_transformed(mapping, entity) and obj.mode == 'TEXTURE_PAINT':
        if uv_layer.name != TEMP_UV:
            return True
        elif TEMP_UV:
            translation, rotation, scale = get_transformation(mapping, entity)
            for i in range(3):
                if obj.mp.texpaint_translation[i] != translation[i]:
                    return True
                if obj.mp.texpaint_rotation[i] != rotation[i]:
                    return True
                if obj.mp.texpaint_scale[i] != scale[i]:
                    return True

    # Check if current active uv matched with current entity uv
    elif uv_name in uv_layers and uv_name != uv_layer.name:
        return True

    return False

def check_uvmap_on_other_objects_with_same_mat(mat, uv_name, set_active=True):
    """
    Check and create UV map on other objects sharing the same material.

    Ensures all mesh objects using the specified material have the required UV
    map, creating it if missing.

    Parameters:
        mat: Blender material to check
        uv_name: Name of the UV map to check/create
        set_active (bool): Whether to set the UV map as active (default: True)

    Returns:
        None
    """
    if mat.users > 1 and uv_name != '':
        for ob in get_scene_objects():
            if ob.type != 'MESH': continue
            if mat.name in ob.data.materials:
                uvls = get_uv_layers(ob)
                if uv_name not in uvls:
                    uvl = uvls.new(name=uv_name)
                    if set_active:
                        uvls.active = uvl

def check_colorid_vcol(objs, set_as_active=False):
    """
    Check and create color ID vertex color on objects if missing.

    Ensures all specified objects have a color ID vertex color layer, creating
    it with black fill color if it doesn't exist.

    Parameters:
        objs: List of Blender objects to check
        set_as_active (bool): Whether to set the vertex color as active (default: False)

    Returns:
        None
    """
    for o in objs:
        vcols = get_vertex_colors(o)
        vcol = vcols.get(COLOR_ID_VCOL_NAME)
        if not vcol:
            try:
                vcol = new_vertex_color(o, COLOR_ID_VCOL_NAME, color_fill=(0.0, 0.0, 0.0, 1.0))
                #set_active_vertex_color(o, vcol)
            except Exception as e: logger.error("Error checking color ID vertex color: %s", e)

        if vcol and set_as_active:
            set_active_vertex_color(o, vcol)

def is_colorid_already_being_used(mp, color_id):
    """
    Check if a color ID is already in use by any mask.

    Compares the given color ID against all mask color IDs within the paint layers
    to detect duplicates within tolerance.

    Parameters:
        mp: MPaint node tree data
        color_id: RGB color tuple to check (r, g, b)

    Returns:
        bool: True if color ID is already in use, False otherwise
    """
    for l in mp.layers:
        for m in l.masks:
            mcol = get_mask_color_id_color(m)
            if abs(mcol[0]-color_id[0]) < COLORID_TOLERANCE and abs(mcol[1]-color_id[1]) < COLORID_TOLERANCE and abs(mcol[2]-color_id[2]) < COLORID_TOLERANCE:
                return True
    return False

def is_colorid_vcol_still_being_used(objs):
    """
    Check if color ID vertex colors are still being used by any material masks.

    Scans all materials on the given objects to determine if any masks are using
    color ID type, indicating the vertex color is still needed.

    Parameters:
        objs: List of Blender objects to check

    Returns:
        bool: True if color ID vertex color is still in use, False otherwise
    """
    for o in objs:
        for m in o.data.materials:
            for n in m.node_tree.nodes:
                if n.type == 'GROUP' and n.node_tree and n.node_tree.mp.is_mpaint_node:
                    for l in n.node_tree.mp.layers:
                        for ma in l.masks:
                            if ma.type == 'COLOR_ID':
                                return True

    return False

def is_image_source_non_color(image, source):
    """
    Check if an image source uses non-color color space.

    Determines if the image is set to non-color data (e.g., for normal maps or
    data textures), excluding float-type generated images.

    Parameters:
        image: Blender image object
        source: Image source type (currently unused in function)

    Returns:
        bool: True if image uses non-color space, False otherwise
    """
    return image.colorspace_settings.name == get_noncolor_name() and not (image.is_float and image.source == 'GENERATED')

def any_linear_images_problem(mp):
    """
    Check if any layers have gamma/linear conversion issues.

    Detects mismatches between expected gamma values and actual linear node
    configurations for layers, channels, and masks.

    Parameters:
        mp: MPaint node tree data

    Returns:
        bool: True if linear image problems detected, False otherwise
    """
    for layer in mp.layers:
        if not get_layer_enabled(layer): continue
        layer_tree = get_tree(layer)

        for i, ch in enumerate(layer.channels):
            root_ch = mp.channels[i]
            #if not get_channel_enabled(ch, layer, root_ch): continue

            gamma = get_layer_channel_gamma_value(ch, layer, root_ch)
            source_tree = get_channel_source_tree(ch, layer)
            linear = source_tree.nodes.get(ch.linear)

            if (
                (gamma == 1.0 and linear) or
                (gamma != 1.0 and (not linear or not isclose(linear.inputs[1].default_value, gamma, rel_tol=1e-5)))
                ):
                return True

            if root_ch.type == 'NORMAL':
                gamma_1 = get_layer_channel_normal_gamma_value(ch, layer, root_ch)
                linear_1 = layer_tree.nodes.get(ch.linear_1)
                if (
                    (gamma_1 == 1.0 and linear_1) or
                    (gamma_1 != 1.0 and (not linear_1 or not isclose(linear_1.inputs[1].default_value, gamma_1, rel_tol=1e-5)))
                    ):
                    return True

        for mask in layer.masks:
            source_tree = get_mask_tree(mask)
            gamma = get_layer_mask_gamma_value(mask, mask_tree=source_tree)
            linear = source_tree.nodes.get(mask.linear)
            if (
                (gamma == 1.0 and linear) or
                (gamma != 1.0 and (not linear or not isclose(linear.inputs[1].default_value, gamma, rel_tol=1e-5)))
                ):
                return True

        gamma = get_layer_gamma_value(layer)
        source_tree = get_source_tree(layer)
        linear = source_tree.nodes.get(layer.linear)

        if (
            (gamma == 1.0 and linear) or
            (gamma != 1.0 and (not linear or not isclose(linear.inputs[1].default_value, gamma, rel_tol=1e-5)))
            ):
            return True

    return False

def check_entity_image_flip_y(entity):
    """
    Check and update flip Y node for entity images.

    Creates or removes a Y-axis flip node based on whether the entity is an image
    that needs vertical flipping (for layers or normal map channels).

    Parameters:
        entity: Layer or channel entity to check

    Returns:
        Layer: The layer object if processing succeeded, None otherwise
    """
    mp = entity.id_data.mp

    m1 = re.match(r'mp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]$', entity.path_from_id())

    if m1:
        layer = entity
        tree = get_source_tree(layer)
        flip_y_needed = layer.image_flip_y and layer.type == 'IMAGE'

    elif m2:
        layer = mp.layers[int(m2.group(1))]
        ch = entity
        tree = get_tree(layer)
        flip_y_needed = ch.image_flip_y and ch.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'} and ch.override_1 and ch.override_1_type == 'IMAGE'
    else:
        return None

    if flip_y_needed:
        flip_y = check_new_node(tree, entity, 'flip_y', 'ShaderNodeGroup', 'Flip Y')
        flip_y.node_tree = get_node_tree_lib(FLIP_Y)
    else:
        remove_node(tree, entity, 'flip_y')

    return layer



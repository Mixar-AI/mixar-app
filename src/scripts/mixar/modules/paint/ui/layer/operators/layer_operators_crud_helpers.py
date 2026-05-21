# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for layer CRUD operators"""

import random
import time

import bpy

from ....procedural_materials import material_registry
from ....core.element.check_elements import is_colorid_already_being_used
from ....core.element.create_vcol import new_vertex_color
from ....core.element.get_elements import (
    get_default_uv_name,
    get_vertex_color_names,
)
from ....core.element.update_image import update_image_editor_image
from ....core.element.update_vcol import set_active_vertex_color
from ....core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_mp_nodes
from ....core.layer.layer_utils import get_uv_layers
from ....core.layer.mappings import is_mapping_possible
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.node_utils import (
    get_active_mpaint_node,
    get_vertex_colors,
)
from ....utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_scene_objects,
    get_srgb_name,
    get_unique_name,
    get_user_preferences,
)
from ....utils.common import (
    get_layer_type_items_callback,
    is_object_work_with_uv,
)
from ....utils.constants import (
    COLORID_TOLERANCE,
    TEMP_UV,
)
from ...image_atlas.image_atlas_utils import (
    clear_unused_segments,
    get_set_image_atlas_segment,
    set_segment_mapping,
)
from ...udim.udim_operators_helper import fill_tile
from ...udim.udim_utils import (
    get_set_udim_atlas_segment,
    get_tile_numbers,
    initial_pack_udim,
)
from mixar.config.logging_config import get_logger

from ....core.element.update_uv import refresh_temp_uv

logger = get_logger(__name__)


def invoke_new_layer(operator, context, event):
    """Handle the invoke logic for MNewLayer operator."""
    from ..helpers.layer_ui_helpers import DEFAULT_NEW_VCOL_SUFFIX

    logger.debug(f"MNewLayer.invoke() called with type: '{operator.type}'")

    mpup = get_user_preferences()
    node = get_active_mpaint_node()
    mp = operator.mp = node.node_tree.mp
    obj = get_active_object()

    if operator.type == "IMAGE":
        name = "Paint Layer"
        items = bpy.data.images
    elif operator.type == "VCOL" and obj.type == "MESH":
        name = obj.active_material.name + DEFAULT_NEW_VCOL_SUFFIX
        items = get_vertex_color_names(obj)
    elif operator.type == "PROCEDURAL" and operator.procedural_material_id:
        # For procedural materials, get the name from the registry
        material = material_registry.get_material(operator.procedural_material_id)
        name = material.name if material else "Procedural Layer"
        items = mp.layers
    else:
        # Get dynamic layer type items that include procedural materials
        all_items = get_layer_type_items_callback()
        logger.debug(f"MNewLayer.invoke() - Layer type: '{operator.type}'")
        logger.debug(f"Available types: {[i[0] for i in all_items[:15]]}")
        matching = [i[1] for i in all_items if i[0] == operator.type]
        if matching:
            name = matching[0]
            logger.debug(f"Found matching name: '{name}'")
        else:
            logger.warning(f"Layer type '{operator.type}' not found in layer type items!")
            logger.warning(f"Available types: {[i[0] for i in all_items]}")
            name = operator.type  # Fallback to the type itself
        items = mp.layers

    # Use user preference default image size
    if mpup.default_image_resolution == "CUSTOM":
        operator.use_custom_resolution = True
        operator.width = operator.height = mpup.default_new_image_size
        operator.mask_use_custom_resolution = True
        operator.mask_width = operator.mask_height = mpup.default_new_image_size
    elif mpup.default_image_resolution != "DEFAULT":
        operator.image_resolution = mpup.default_image_resolution
        operator.mask_image_resolution = mpup.default_image_resolution

    # Make sure add mask is inactive
    if operator.type not in {"COLOR", "BACKGROUND"}:
        operator.add_mask = False

    # Set spread fix by default on vertex color layer
    operator.use_divider_alpha = True if operator.type in {"VCOL"} else False

    # Use white color mask as default for group
    if operator.type == "GROUP":
        operator.mask_color = "WHITE"
    else:
        operator.mask_color = "BLACK"

    # Default normal map type is bump map
    operator.normal_map_type = "BUMP_MAP"

    # Fake lighting default blend type is add
    if operator.type in {"HEMI", "EDGE_DETECT"}:
        operator.blend_type = "ADD"
    if operator.type == "AO":
        operator.blend_type = "MULTIPLY"
    else:
        operator.blend_type = "MIX"

    # Disable use previous normal for edge detect since it has very little effect
    if operator.type == "EDGE_DETECT":
        operator.hemi_use_prev_normal = False

    if operator.add_mask and operator.mask_type == "EDGE_DETECT":
        operator.mask_use_prev_normal = False

    # Layer name
    operator.name = get_unique_name(name, items)

    # Layer name must also unique
    if operator.type == "IMAGE":
        operator.name = get_unique_name(operator.name, mp.layers)

    # Make sure decal is off when adding non mappable layer
    if not is_mapping_possible(operator.type) and operator.texcoord_type == "Decal":
        operator.texcoord_type = "UV"
        operator.mask_texcoord_type = "UV"

    # Check if color id already being used
    while True:
        # Use color id tolerance value as lowest value to avoid pure black color
        operator.mask_color_id = (
            random.uniform(COLORID_TOLERANCE, 1.0),
            random.uniform(COLORID_TOLERANCE, 1.0),
            random.uniform(COLORID_TOLERANCE, 1.0),
        )
        if not is_colorid_already_being_used(mp, operator.mask_color_id):
            break

    if not is_object_work_with_uv(obj):
        operator.texcoord_type = "Generated"
        operator.mask_texcoord_type = "Generated"

    if obj.type == "MESH":
        uv_name = get_default_uv_name(obj, mp)
        operator.uv_map = uv_name
        if operator.add_mask:
            operator.mask_uv_name = uv_name

        # UV Map collections update
        operator.uv_map_coll.clear()
        for uv in get_uv_layers(obj):
            if not uv.name.startswith(TEMP_UV):
                operator.uv_map_coll.add().name = uv.name

    if operator.default_layer:
        return operator.execute(context)

    if get_user_preferences().skip_property_popups and not event.shift:
        return operator.execute(context)

    return context.window_manager.invoke_props_dialog(operator, width=320)


def execute_new_layer(operator, context):
    """Handle the execute logic for MNewLayer operator."""
    from ..helpers.layer_ui_helpers import add_new_layer

    T = time.time()

    wm = context.window_manager
    obj = get_active_object()
    mat = get_active_material(obj)
    node = get_active_mpaint_node()
    mp = node.node_tree.mp
    mpui = context.window_manager.mpui
    vcol_names = get_vertex_color_names(obj)

    # Check if object is not a mesh
    if (
        operator.type == "VCOL" or (operator.add_mask and operator.mask_type == "VCOL")
    ) and obj.type != "MESH":
        operator.report({"ERROR"}, "Vertex color only works with mesh object!")
        return {"CANCELLED"}

    # Check if layer with same name is already available
    if operator.type == "IMAGE":
        same_name = [i for i in bpy.data.images if i.name == operator.name]
    elif operator.type == "VCOL":
        same_name = [i for i in vcol_names if i == operator.name]
    else:
        same_name = [lay for lay in mp.layers if lay.name == operator.name]
    if same_name:
        if operator.type == "IMAGE":
            operator.report(
                {"ERROR"}, "Image named '" + operator.name + "' is already available!"
            )
        elif operator.type == "VCOL":
            operator.report(
                {"ERROR"},
                "Vertex Color named '" + operator.name + "' is already available!",
            )
        else:
            operator.report(
                {"ERROR"}, "Layer named '" + operator.name + "' is already available!"
            )
        return {"CANCELLED"}

    # Clearing unused image atlas segments
    img_atlas = operator.get_to_be_cleared_image_atlas(context, mp)
    if img_atlas:
        clear_unused_segments(img_atlas.yia)

    # Get channel index
    try:
        channel_idx = int(operator.channel_idx)
    except:
        channel_idx = 0

    img = None
    segment = None
    if operator.type == "IMAGE":
        img, segment = _create_image_layer(operator, mat)
        update_image_editor_image(context, img)

    vcol = None
    if operator.type == "VCOL":
        vcol = _create_vcol_layer(operator, obj, mat)

    mp.halt_update = True

    # For PROCEDURAL type, use procedural_material_id as layer_type
    layer_type_param = operator.procedural_material_id if operator.type == 'PROCEDURAL' and operator.procedural_material_id else operator.type

    layer = add_new_layer(
        node.node_tree,
        operator.name,
        layer_type_param,
        channel_idx,
        operator.blend_type,
        operator.normal_blend_type,
        operator.normal_map_type,
        operator.texcoord_type,
        uv_name=operator.uv_map,
        image=img,
        vcol=vcol,
        segment=segment,
        solid_color=operator.solid_color,
        add_mask=operator.add_mask,
        mask_type=operator.mask_type,
        mask_image_filepath=operator.mask_image_filepath,
        mask_relative=operator.mask_relative,
        mask_texcoord_type=operator.mask_texcoord_type,
        mask_color=operator.mask_color,
        mask_use_hdr=operator.mask_use_hdr,
        mask_uv_name=operator.mask_uv_name,
        mask_width=operator.mask_width,
        mask_height=operator.mask_height,
        use_image_atlas_for_mask=operator.use_image_atlas_for_mask,
        hemi_space=operator.hemi_space,
        hemi_use_prev_normal=operator.hemi_use_prev_normal,
        mask_color_id=operator.mask_color_id,
        mask_vcol_fill=operator.mask_vcol_fill,
        mask_vcol_data_type=operator.mask_vcol_data_type,
        mask_vcol_domain=operator.mask_vcol_domain,
        use_divider_alpha=operator.use_divider_alpha,
        use_udim_for_mask=operator.use_udim_for_mask,
        interpolation=operator.interpolation,
        mask_interpolation=operator.mask_interpolation,
        mask_edge_detect_radius=operator.mask_edge_detect_radius,
        edge_detect_radius=operator.edge_detect_radius,
        mask_use_prev_normal=operator.mask_use_prev_normal,
        ao_distance=operator.ao_distance,
    )

    if segment:
        set_segment_mapping(layer, segment, img)
        refresh_temp_uv(obj, layer)

    mp.halt_update = False

    # Reconnect and rearrange nodes
    reconnect_mp_nodes(node.node_tree)
    rearrange_mp_nodes(node.node_tree)

    # Update UI - use global expand states in mixar_ui
    _update_ui_after_layer_creation(operator, wm, mp, mpui, layer, channel_idx)

    logger.info(
        "Layer %s created in %s ms!",
        layer.name, "{:0.2f}".format((time.time() - T) * 1000)
    )
    wm.mptimer.time = str(time.time())

    return {"FINISHED"}


def _create_image_layer(operator, mat):
    """Create image layer data."""
    alpha = True
    color = (0, 0, 0, 0)
    img = None
    segment = None

    if operator.use_udim:
        objs = get_all_objects_with_same_materials(mat)
        tilenums = get_tile_numbers(objs, operator.uv_map)
    else:
        tilenums = None

    if operator.use_image_atlas:
        if operator.use_udim:
            from ....core.node.node_utils import get_active_mpaint_node
            node = get_active_mpaint_node()
            mp = node.node_tree.mp
            segment = get_set_udim_atlas_segment(
                tilenums,
                operator.width,
                operator.height,
                color,
                get_srgb_name(),
                operator.hdr,
                mp,
            )
        else:
            from ....core.node.node_utils import get_active_mpaint_node
            node = get_active_mpaint_node()
            mp = node.node_tree.mp
            segment = get_set_image_atlas_segment(
                operator.width, operator.height, "TRANSPARENT", operator.hdr, mp=mp
            )
        img = segment.id_data
    else:
        if operator.use_udim:
            img = bpy.data.images.new(
                name=operator.name,
                width=operator.width,
                height=operator.height,
                alpha=alpha,
                float_buffer=operator.hdr,
                tiled=True,
            )

            # Fill tiles
            for tilenum in tilenums:
                fill_tile(img, tilenum, color, operator.width, operator.height)
            initial_pack_udim(img, color)
        else:
            img = bpy.data.images.new(
                name=operator.name,
                width=operator.width,
                height=operator.height,
                alpha=alpha,
                float_buffer=operator.hdr,
            )

            img.generated_type = "BLANK"
            img.generated_color = color
            if hasattr(img, "use_alpha"):
                img.use_alpha = True

        # Set alpha mode to premultiplied
        if img.is_float:
            img.alpha_mode = "PREMUL"

    return img, segment


def _create_vcol_layer(operator, obj, mat):
    """Create vertex color layer data."""
    vcol = None
    objs = [obj] if obj.type == "MESH" else []
    if mat.users > 1:
        for o in get_scene_objects():
            if o.type != "MESH":
                continue
            if mat.name in o.data.materials and o not in objs:
                objs.append(o)

    for o in objs:
        if operator.name not in get_vertex_colors(o):
            color = (0.0, 0.0, 0.0, 0.0)
            vcol = new_vertex_color(
                o,
                operator.name,
                operator.vcol_data_type,
                operator.vcol_domain,
                color_fill=color,
            )
            set_active_vertex_color(o, vcol)

    return vcol


def _update_ui_after_layer_creation(operator, wm, mp, mpui, layer, channel_idx):
    """Update UI state after layer creation."""
    if hasattr(wm, 'mixar_ui'):
        if operator.type not in {"IMAGE", "VCOL", "COLOR", "BACKGROUND", "GROUP"}:
            wm.mixar_ui.expand_source = True
        else:
            wm.mixar_ui.expand_source = False

        if operator.channel_idx != "-1":
            wm.mixar_ui.expand_channels = False
            if mp.channels[channel_idx].type == "NORMAL":
                layer.channels[channel_idx].expand_content = True
        else:
            wm.mixar_ui.expand_channels = True

        loaded_image_mask = operator.mask_type == "IMAGE" and operator.mask_image_filepath
        if operator.add_mask and (loaded_image_mask or operator.mask_type == "EDGE_DETECT"):
            wm.mixar_ui.expand_masks = True
            layer.masks[0].expand_content = True
            if operator.mask_type == "EDGE_DETECT":
                layer.masks[0].expand_source = True
            elif loaded_image_mask:
                layer.masks[0].expand_vector = True
        else:
            wm.mixar_ui.expand_masks = False
            for i, mask in enumerate(layer.masks):
                mask.expand_content = False

    # Legacy mpui properties (MLayerUI may not be registered yet on first run)
    if hasattr(mpui, 'layer_ui'):
        if operator.type not in {"IMAGE", "VCOL", "COLOR", "BACKGROUND", "GROUP"}:
            mpui.layer_ui.expand_content = True
        else:
            mpui.layer_ui.expand_content = False
        mpui.layer_ui.expand_vector = False

    mpui.need_update = True

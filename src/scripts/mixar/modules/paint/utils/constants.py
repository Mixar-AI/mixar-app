# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Constants for the paint module.

This module re-exports all constants from sub-modules for backward compatibility.
Constants are organized into the following categories:
- node_constants: Node-related constants (prefixes, suffixes, tree structure)
- channel_constants: Channel types, socket types, colorspaces, blend modes
- layer_constants: Layer types, items, labels, source types
- mask_constants: Mask types, items, labels
- bake_constants: Bake types, items, labels, suffixes
- texture_constants: Texture coordinates, image resolution, paint tools
- ui_constants: UI layout scale factors, icons, channel detection sets
- channel_detection: Channel type detection utilities
"""

# Re-export all constants from node_constants
from .node_constants import (
    MP_GROUP_SUFFIX,
    MP_GROUP_PREFIX,
    FEATURE_NAME,
    GROUP_NODE_NAME,
    LAYERGROUP_PREFIX,
    MASKGROUP_PREFIX,
    INFO_PREFIX,
    TREE_START,
    TREE_END,
    ONE_VALUE,
    ZERO_VALUE,
    MOD_TREE_START,
    MOD_TREE_END,
    TEXCOORD,
    GEOMETRY,
    BAKED_PARALLAX,
    BAKED_PARALLAX_FILTER,
    PARALLAX_PREP_SUFFIX,
    PARALLAX,
    HEIGHT_MAP,
    START_UV,
    DELTA_UV,
    CURRENT_UV,
    ITERATE_GROUP,
    PARALLAX_DIVIDER,
    TEXCOORD_IO_PREFIX,
    PARALLAX_MIX_PREFIX,
    PARALLAX_DELTA_PREFIX,
    PARALLAX_CURRENT_PREFIX,
    PARALLAX_CURRENT_MIX_PREFIX,
    LAYER_VIEWER,
    LAYER_ALPHA_VIEWER,
    EMISSION_VIEWER,
    AO_MULTIPLY,
    FLOW_VCOL,
    COLOR_ID_VCOL_NAME,
    TANGENT_SIGN_PREFIX,
    CACHE_TANGENT_IMAGE_SUFFIX,
    CACHE_BITANGENT_IMAGE_SUFFIX,
    BLENDER_28_GROUP_INPUT_HACK,
    MAX_VERTEX_DATA,
    TEMP_UV,
    BUMP_MULTIPLY_TWEAK,
    GAMMA,
    io_suffix,
    io_names,
    layer_node_bl_idnames,
    texture_node_types,
    possible_object_types,
)

# Re-export all constants from channel_constants
from .channel_constants import (
    channel_socket_types,
    channel_socket_custom_icon_names,
    CHANNEL_SOCKET_TYPES,
    channel_socket_input_bl_idnames,
    channel_socket_output_bl_idnames,
    COLORSPACE_LINEAR,
    COLORSPACE_SRGB,
    colorspace_items,
    blend_type_labels,
    normal_blend_items,
    normal_blend_labels,
    normal_space_items,
    height_blend_items,
    normal_type_labels,
    channel_override_type_items,
    get_channel_override_type_items,
    channel_override_1_type_items,
    channel_override_labels,
    limited_mask_blend_types,
    math_method_items,
    vcol_domain_items,
    vcol_data_type_items,
    rgba_letters,
    nsew_letters,
    neighbor_directions,
    COLORID_TOLERANCE,
    PBR_CHANNELS,
    BLEND_MODES,
)

# Re-export all constants from layer_constants
from .layer_constants import (
    layer_type_items,
    layer_source_type_items,
    projection_type_items,
    projection_axis_items,
    uv_extension_items,
    layer_type_labels,
    hemi_space_items,
    voronoi_feature_items,
)

# Re-export all constants from mask_constants
from .mask_constants import (
    mask_type_items,
    mask_type_labels,
)

# Re-export all constants from bake_constants
from .bake_constants import (
    bake_type_items,
    bake_type_labels,
    bake_type_suffixes,
    EXPORT_FORMAT_EXTENSIONS,
    EXPORT_FILE_FORMAT_ITEMS,
    INVALID_FILENAME_CHARS,
)

# Re-export utility functions from bake_utils
from .bake_utils import sanitize_filename

# Re-export all constants from texture_constants
from .texture_constants import (
    texcoord_lists,
    texcoord_type_items,
    mask_texcoord_type_items,
    interpolation_type_items,
    image_resolution_items,
    RESOLUTION_OPTIONS,
    DEFAULT_RESOLUTION,
    valid_image_extensions,
    eraser_names,
    tex_eraser_asset_names,
    tex_default_brushes,
)

# Re-export all constants from ui_constants
from .ui_constants import (
    UI_SCALE_Y,
    UI_HEADER_SCALE_Y,
    LABEL_SPLIT_FACTOR,
    NAME_SPLIT_FACTOR,
    SEPARATOR_FACTOR,
    SECTION_SEPARATOR_FACTOR,
    IMAGE_BTN_SCALE_X,
    Icons,
    AO_CHANNEL_NAMES,
    EMISSION_CHANNEL_NAMES,
    OverrideDefaults,
    BUMP_NORMAL_TYPES,
    NORMAL_STRENGTH_TYPES,
)

# Re-export channel detection utilities
from .channel_detection import (
    is_ao_channel,
    is_emission_channel,
    is_color_channel,
    get_override_default_value,
    get_override_default_color,
)

# Define __all__ for explicit exports
__all__ = [
    # Node constants
    "MP_GROUP_SUFFIX",
    "MP_GROUP_PREFIX",
    "FEATURE_NAME",
    "GROUP_NODE_NAME",
    "LAYERGROUP_PREFIX",
    "MASKGROUP_PREFIX",
    "INFO_PREFIX",
    "TREE_START",
    "TREE_END",
    "ONE_VALUE",
    "ZERO_VALUE",
    "MOD_TREE_START",
    "MOD_TREE_END",
    "TEXCOORD",
    "GEOMETRY",
    "BAKED_PARALLAX",
    "BAKED_PARALLAX_FILTER",
    "PARALLAX_PREP_SUFFIX",
    "PARALLAX",
    "HEIGHT_MAP",
    "START_UV",
    "DELTA_UV",
    "CURRENT_UV",
    "ITERATE_GROUP",
    "PARALLAX_DIVIDER",
    "TEXCOORD_IO_PREFIX",
    "PARALLAX_MIX_PREFIX",
    "PARALLAX_DELTA_PREFIX",
    "PARALLAX_CURRENT_PREFIX",
    "PARALLAX_CURRENT_MIX_PREFIX",
    "LAYER_VIEWER",
    "LAYER_ALPHA_VIEWER",
    "EMISSION_VIEWER",
    "AO_MULTIPLY",
    "FLOW_VCOL",
    "COLOR_ID_VCOL_NAME",
    "TANGENT_SIGN_PREFIX",
    "CACHE_TANGENT_IMAGE_SUFFIX",
    "CACHE_BITANGENT_IMAGE_SUFFIX",
    "BLENDER_28_GROUP_INPUT_HACK",
    "MAX_VERTEX_DATA",
    "TEMP_UV",
    "BUMP_MULTIPLY_TWEAK",
    "GAMMA",
    "io_suffix",
    "io_names",
    "layer_node_bl_idnames",
    "texture_node_types",
    "possible_object_types",
    # Channel constants
    "channel_socket_types",
    "channel_socket_custom_icon_names",
    "CHANNEL_SOCKET_TYPES",
    "channel_socket_input_bl_idnames",
    "channel_socket_output_bl_idnames",
    "COLORSPACE_LINEAR",
    "COLORSPACE_SRGB",
    "colorspace_items",
    "blend_type_labels",
    "normal_blend_items",
    "normal_blend_labels",
    "normal_space_items",
    "height_blend_items",
    "normal_type_labels",
    "channel_override_type_items",
    "get_channel_override_type_items",
    "channel_override_1_type_items",
    "channel_override_labels",
    "limited_mask_blend_types",
    "math_method_items",
    "vcol_domain_items",
    "vcol_data_type_items",
    "rgba_letters",
    "nsew_letters",
    "neighbor_directions",
    "COLORID_TOLERANCE",
    "PBR_CHANNELS",
    "BLEND_MODES",
    # Layer constants
    "layer_type_items",
    "layer_source_type_items",
    "projection_type_items",
    "projection_axis_items",
    "uv_extension_items",
    "layer_type_labels",
    "hemi_space_items",
    "voronoi_feature_items",
    # Mask constants
    "mask_type_items",
    "mask_type_labels",
    # Bake constants
    "bake_type_items",
    "bake_type_labels",
    "bake_type_suffixes",
    "EXPORT_FORMAT_EXTENSIONS",
    "EXPORT_FILE_FORMAT_ITEMS",
    "INVALID_FILENAME_CHARS",
    "sanitize_filename",
    # Texture constants
    "texcoord_lists",
    "texcoord_type_items",
    "mask_texcoord_type_items",
    "interpolation_type_items",
    "image_resolution_items",
    "RESOLUTION_OPTIONS",
    "DEFAULT_RESOLUTION",
    "valid_image_extensions",
    "eraser_names",
    "tex_eraser_asset_names",
    "tex_default_brushes",
    # UI constants
    "UI_SCALE_Y",
    "UI_HEADER_SCALE_Y",
    "LABEL_SPLIT_FACTOR",
    "NAME_SPLIT_FACTOR",
    "SEPARATOR_FACTOR",
    "SECTION_SEPARATOR_FACTOR",
    "IMAGE_BTN_SCALE_X",
    "Icons",
    "AO_CHANNEL_NAMES",
    "EMISSION_CHANNEL_NAMES",
    "OverrideDefaults",
    "BUMP_NORMAL_TYPES",
    "NORMAL_STRENGTH_TYPES",
    # Channel detection utilities
    "is_ao_channel",
    "is_emission_channel",
    "is_color_channel",
    "get_override_default_value",
    "get_override_default_color",
]

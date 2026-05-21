# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Channel-related constants for the paint module.

Contains constants for channel types, socket types, colorspaces, and blend modes.
"""

# Channel socket types
channel_socket_types = {
    "RGB": "RGBA",
    "VALUE": "VALUE",
    "NORMAL": "VECTOR",
}

# Channel socket custom icon names
channel_socket_custom_icon_names = {
    "RGB": "rgb_channel",
    "VALUE": "value_channel",
    "NORMAL": "vector_channel",
}

# Channel socket types mapping
CHANNEL_SOCKET_TYPES = {
    "RGB": "NodeSocketColor",
    "VALUE": "NodeSocketFloat",
    "NORMAL": "NodeSocketVector",
}

# Channel socket input Blender ID names
channel_socket_input_bl_idnames = {
    "RGB": "NodeSocketColor",
    "VALUE": "NodeSocketFloatFactor",
    "NORMAL": "NodeSocketVector",
}

# Channel socket output Blender ID names
channel_socket_output_bl_idnames = {
    "RGB": "NodeSocketColor",
    "VALUE": "NodeSocketFloat",
    "NORMAL": "NodeSocketVector",
}

# Colorspace constants
COLORSPACE_LINEAR = "LINEAR"
COLORSPACE_SRGB = "SRGB"

colorspace_items = (("LINEAR", "Non-Color Data", ""), ("SRGB", "Color Data", ""))

# Blend type labels
blend_type_labels = {
    "MIX": "Mix",
    "ADD": "Add",
    "SUBTRACT": "Subtract",
    "MULTIPLY": "Multiply",
    "SCREEN": "Screen",
    "OVERLAY": "Overlay",
    "DIFFERENCE": "Difference",
    "DIVIDE": "Divide",
    "DARKEN": "Darken",
    "LIGHTEN": "Lighten",
    "HUE": "Hue",
    "SATURATION": "Saturation",
    "VALUE": "Value",
    "COLOR": "Color",
    "SOFT_LIGHT": "Soft Light",
    "LINEAR_LIGHT": "Linear Light",
    "DODGE": "Dodge",
    "BURN": "Burn",
    "EXCLUSION": "Exclusion",
}

# Normal blend items
normal_blend_items = (
    ("MIX", "Mix", ""),
    ("OVERLAY", "Add", ""),
    ("COMPARE", "Compare Height", ""),
)

# Normal blend labels
normal_blend_labels = {
    "MIX": "Mix",
    "OVERLAY": "Overlay",
    "COMPARE": "Compare Height",
}

# Normal space items
normal_space_items = (
    ("TANGENT", "Tangent Space", "Tangent space normal mapping"),
    ("OBJECT", "Object Space", "Object space normal mapping"),
    ("WORLD", "World Space", "World space normal mapping"),
    (
        "BLENDER_OBJECT",
        "Blender Object Space",
        "Object space normal mapping, compatible with Blender render baking",
    ),
    (
        "BLENDER_WORLD",
        "Blender World Space",
        "World space normal mapping, compatible with Blender render baking",
    ),
)

# Height blend items
height_blend_items = (
    ("REPLACE", "Replace", ""),
    ("COMPARE", "Compare", ""),
    ("ADD", "Add", ""),
)

# Normal type labels
normal_type_labels = {
    "BUMP_MAP": "Bump",
    "NORMAL_MAP": "Normal",
    "BUMP_NORMAL_MAP": "Bump + Normal",
    "VECTOR_DISPLACEMENT_MAP": "Vector Displacement",
}

# Channel override type items - 4 options for fill/procedural layers
# Defines how each channel gets its source data
# Static items for paint layers (IMAGE type)
channel_override_type_items = (
    ("LAYER", "Brush", "Use layer's source texture/color"),
    ("PASSTHROUGH", "Pass-through", "Use previous layer's values (disable for this layer)"),
    ("OVERRIDE", "Custom", "Use slider/color value"),
    ("IMAGE", "Image", "Use image texture"),
)

# Items for fill layers (COLOR type) - uses "Layer Color" instead of "Brush"
channel_override_type_items_fill = (
    ("LAYER", "Layer Color", "Use layer's source color"),
    ("PASSTHROUGH", "Pass-through", "Use previous layer's values (disable for this layer)"),
    ("OVERRIDE", "Custom", "Use slider/color value"),
    ("IMAGE", "Image", "Use image texture"),
)

# Items for procedural layers (PROCEDURAL type) - uses "Procedural Output"
channel_override_type_items_procedural = (
    ("LAYER", "Procedural Output", "Use procedural material output"),
    ("PASSTHROUGH", "Pass-through", "Use previous layer's values (disable for this layer)"),
    ("OVERRIDE", "Custom", "Use slider/color value"),
    ("IMAGE", "Image", "Use image texture"),
)


def get_channel_override_type_items(self, context):
    """Dynamic enum items for channel override type based on layer type.

    Returns different labels based on layer type:
    - Fill layers (COLOR): "Layer Color"
    - Procedural layers (PROCEDURAL): "Procedural Output"
    - Paint layers (IMAGE): "Brush"
    """
    import re

    try:
        # Get layer from channel path
        mp = self.id_data.mp
        m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
        if m:
            layer_idx = int(m.group(1))
            if layer_idx < len(mp.layers):
                layer = mp.layers[layer_idx]
                if layer.type == 'COLOR':
                    return channel_override_type_items_fill
                elif layer.type == 'PROCEDURAL':
                    return channel_override_type_items_procedural
    except Exception:
        pass

    return channel_override_type_items

# Override 1 will only use default value or image for now
# Used for normal map override in bump+normal channels
channel_override_1_type_items = (
    ("DEFAULT", "Default", "Use default normal color"),
    ("IMAGE", "Image", "Use image texture"),
)

# DEPRECATED: Legacy override type items (backward compatibility with v1 schema)
# Will be removed in v3.0. Use channel_override_type_items instead.
# Deprecation date: 2024-Q4
channel_override_type_items_legacy = (
    ("DEFAULT", "Default", ""),
    ("IMAGE", "Image", ""),
)

# Channel override labels
# Used for per-channel override display names
channel_override_labels = {
    "DEFAULT": "Default",
    "IMAGE": "Image",
    "BRICK": "Brick",
    "CHECKER": "Checker",
    "GRADIENT": "Gradient",
    "MAGIC": "Magic",
    "MUSGRAVE": "Musgrave",
    "NOISE": "Noise",
    "VORONOI": "Voronoi",
    "WAVE": "Wave",
    "VCOL": "Vertex Color",
    "HEMI": "Fake Lighting",
    "GABOR": "Gabor",
}

# Limited mask blend types
limited_mask_blend_types = {
    "ADD",
    "DIVIDE",
    "SCREEN",
    "MIX",
    "DIFFERENCE",
    "LIGHTEN",
    "VALUE",
    "LINEAR_LIGHT",
}

# Math method items
math_method_items = (
    ("ADD", "Add", ""),
    ("SUBTRACT", "Subtract", ""),
    ("MULTIPLY", "Multiply", ""),
    ("DIVIDE", "Divide", ""),
    ("POWER", "Power", ""),
    ("LOGARITHM", "Logarithm", ""),
)

# Vertex color domain items
vcol_domain_items = (
    ("POINT", "Vertex", ""),
    ("CORNER", "Face Corner", ""),
)

# Vertex color data type items
vcol_data_type_items = (
    ("FLOAT_COLOR", "Color", ""),
    ("BYTE_COLOR", "Byte Color", ""),
)

# Color letters
rgba_letters = ["r", "g", "b", "a"]
nsew_letters = ["n", "s", "e", "w"]
neighbor_directions = ["n", "s", "e", "w"]

# Color ID tolerance
COLORID_TOLERANCE = 0.003906  # 1/256

# PBR Channels (merged from texturing module)
PBR_CHANNELS = [
    ('BASE_COLOR', 'Base Color', 'Albedo/Diffuse color'),
    ('METALLIC', 'Metallic', 'Metallic value'),
    ('ROUGHNESS', 'Roughness', 'Surface roughness'),
    ('NORMAL', 'Normal', 'Normal map'),
    ('HEIGHT', 'Height', 'Displacement height'),
    ('AO', 'Ambient Occlusion', 'Ambient occlusion'),
    ('EMISSIVE', 'Emissive', 'Emission color'),
]

# Blend modes (merged from texturing module)
BLEND_MODES = [
    ('NORMAL', 'Normal', 'Normal blending'),
    ('MULTIPLY', 'Multiply', 'Multiply blending'),
    ('SCREEN', 'Screen', 'Screen blending'),
    ('OVERLAY', 'Overlay', 'Overlay blending'),
    ('SOFT_LIGHT', 'Soft Light', 'Soft light blending'),
    ('HARD_LIGHT', 'Hard Light', 'Hard light blending'),
    ('LINEAR_DODGE', 'Add', 'Additive blending'),
]

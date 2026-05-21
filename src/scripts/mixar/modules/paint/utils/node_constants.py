# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Node-related constants for the paint module.

Contains constants for node names, prefixes, suffixes, and tree structure.
"""

# Node group naming
MP_GROUP_SUFFIX = " Mixar"
MP_GROUP_PREFIX = "Mixar "

FEATURE_NAME = "Mixar Paint"
GROUP_NODE_NAME = FEATURE_NAME + " Layers"

# Layer and mask group prefixes
LAYERGROUP_PREFIX = "~yP Layer "
MASKGROUP_PREFIX = "~yP Mask "

# Info prefix for metadata
INFO_PREFIX = "__yp_info_"

# Tree structure nodes
TREE_START = "Group Input"
TREE_END = "Group Output"
ONE_VALUE = "One Value"
ZERO_VALUE = "Zero Value"

# Modifier tree markers
MOD_TREE_START = "__mod_start"
MOD_TREE_END = "__mod_end"

# Special nodes
TEXCOORD = "Texture Coordinate"
GEOMETRY = "Geometry"

# Parallax-related constants
BAKED_PARALLAX = "Baked Parallax"
BAKED_PARALLAX_FILTER = "Baked Parallax Filter"
PARALLAX_PREP_SUFFIX = " Parallax Preparation"
PARALLAX = "Parallax"
HEIGHT_MAP = "Height Map"
START_UV = " Start UV"
DELTA_UV = " Delta UV"
CURRENT_UV = " Current UV"
ITERATE_GROUP = "~yP Iterate Parallax Group"
PARALLAX_DIVIDER = 4

# Parallax IO prefixes
TEXCOORD_IO_PREFIX = "Texcoord "
PARALLAX_MIX_PREFIX = "Parallax Mix "
PARALLAX_DELTA_PREFIX = "Parallax Delta "
PARALLAX_CURRENT_PREFIX = "Parallax Current "
PARALLAX_CURRENT_MIX_PREFIX = "Parallax Current Mix "

# Viewer nodes
LAYER_VIEWER = "_Layer Viewer"
LAYER_ALPHA_VIEWER = "_Layer Alpha Viewer"
EMISSION_VIEWER = "Emission Viewer"

# AO node
AO_MULTIPLY = "yP AO Multiply"

# Vertex color prefixes
FLOW_VCOL = "__flow_"
COLOR_ID_VCOL_NAME = "__yp_color_id"
TANGENT_SIGN_PREFIX = "__tsign_"

# Cache image suffixes
CACHE_TANGENT_IMAGE_SUFFIX = "_YP_CACHE_TANGENT"
CACHE_BITANGENT_IMAGE_SUFFIX = "_YP_CACHE_BITANGENT"

# Misc
BLENDER_28_GROUP_INPUT_HACK = False
MAX_VERTEX_DATA = 8
TEMP_UV = "~TL Temp Paint UV"
BUMP_MULTIPLY_TWEAK = 5
GAMMA = 2.2

# IO suffixes for node groups
io_suffix = {
    "GROUP": " Group",
    "BACKGROUND": " Background",
    "ALPHA": " Alpha",
    "DISPLACEMENT": " Displacement",
    "HEIGHT": " Height",
    "MAX_HEIGHT": " Max Height",
    "VDISP": " Vector Displacement",
    "HEIGHT_ONS": " Height ONS",
    "HEIGHT_EW": " Height EW",
    "UV": " UV",
    "TANGENT": " Tangent",
    "BITANGENT": " Bitangent",
    "HEIGHT_N": " Height N",
    "HEIGHT_S": " Height S",
    "HEIGHT_E": " Height E",
    "HEIGHT_W": " Height W",
}

# IO names for texture coordinates
io_names = {
    "Generated": "Texcoord Generated",
    "Object": "Texcoord Object",
    "Normal": "Texcoord Normal",
    "Camera": "Texcoord Camera",
    "Window": "Texcoord Window",
    "Reflection": "Texcoord Reflection",
    "Decal": "Texcoord Object",
}

# Layer node Blender ID names
layer_node_bl_idnames = {
    "IMAGE": "ShaderNodeTexImage",
    "ENVIRONMENT": "ShaderNodeTexEnvironment",
    "BRICK": "ShaderNodeTexBrick",
    "CHECKER": "ShaderNodeTexChecker",
    "GRADIENT": "ShaderNodeTexGradient",
    "MAGIC": "ShaderNodeTexMagic",
    "MUSGRAVE": "ShaderNodeTexMusgrave",
    "NOISE": "ShaderNodeTexNoise",
    "POINT_DENSITY": "ShaderNodeTexPointDensity",
    "SKY": "ShaderNodeTexSky",
    "VORONOI": "ShaderNodeTexVoronoi",
    "WAVE": "ShaderNodeTexWave",
    "VCOL": "ShaderNodeAttribute",
    "BACKGROUND": "NodeGroupInput",
    "COLOR": "ShaderNodeRGB",
    "GROUP": "NodeGroupInput",
    "HEMI": "ShaderNodeGroup",
    "OBJECT_INDEX": "ShaderNodeGroup",
    "COLOR_ID": "ShaderNodeGroup",
    "BACKFACE": "ShaderNodeNewGeometry",
    "EDGE_DETECT": "ShaderNodeGroup",
    "GABOR": "ShaderNodeTexGabor",
    "MODIFIER": "ShaderNodeGroup",
    "AO": "ShaderNodeAmbientOcclusion",
}

# Texture node types
texture_node_types = {
    "TEX_IMAGE",
    "TEX_BRICK",
    "TEX_ENVIRONMENT",
    "TEX_CHECKER",
    "TEX_GRADIENT",
    "TEX_MAGIC",
    "TEX_MUSGRAVE",
    "TEX_NOISE",
    "TEX_POINTDENSITY",
    "TEX_SKY",
    "TEX_VORONOI",
    "TEX_WAVE",
}

# Possible object types for texturing
possible_object_types = {"MESH", "META", "CURVE", "CURVES", "SURFACE", "FONT"}

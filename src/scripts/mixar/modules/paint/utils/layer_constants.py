# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Layer-related constants for the paint module.

Contains constants for layer types, items, labels, and source types.
"""

from mixar.modules.common.i18n import n_

# Layer type items
layer_type_items = (
    ("IMAGE", "Image", ""),
    ("BRICK", "Brick", ""),
    ("CHECKER", "Checker", ""),
    ("GRADIENT", "Gradient", ""),
    ("MAGIC", "Magic", ""),
    ("MUSGRAVE", "Musgrave", ""),
    ("NOISE", "Noise", ""),
    ("VORONOI", "Voronoi", ""),
    ("WAVE", "Wave", ""),
    ("VCOL", "Vertex Color", ""),
    ("BACKGROUND", "Background", ""),
    ("COLOR", "Fill Layer", ""),
    ("GROUP", "Group", ""),
    ("HEMI", "Fake Lighting", ""),
    ("GABOR", "Gabor", ""),
    ("EDGE_DETECT", "Edge Detect", ""),
    ("AO", "Ambient Occlusion", ""),
)

# Layer source type for Fill layers (switches between solid color, image, material)
layer_source_type_items = (
    ("SOLID_COLOR", "Solid Color", "Use a solid fill color"),
    ("IMAGE", "Image", "Use an image texture"),
    ("MATERIAL", "Material", "Use a procedural material from library"),
)

# Projection type for texture mapping (Substance Painter style)
projection_type_items = (
    ("UV", "UV", "Standard UV mapping"),
    ("TRIPLANAR", "Tri-planar", "Box projection blending between axes"),
    ("PLANAR", "Planar", "Single plane projection"),
    ("SPHERICAL", "Spherical", "Spherical projection"),
    ("CYLINDRICAL", "Cylindrical", "Cylindrical projection"),
    ("DECAL", "Decal", "Project texture as a decal using an empty object"),
)

# UV extension/wrap mode items
uv_extension_items = (
    ("REPEAT", "Repeat", "Tile texture in both directions"),
    ("EXTEND", "Extend", "Extend edge colors"),
    ("CLIP", "Clip", "Clip to texture bounds"),
    ("MIRROR", "Mirror", "Mirror at edges"),
)

# Projection axis items for PLANAR and CYLINDRICAL projections
projection_axis_items = (
    ("X", "X", "Project along X axis"),
    ("Y", "Y", "Project along Y axis"),
    ("Z", "Z", "Project along Z axis (default)"),
)

# Layer type labels
layer_type_labels = {
    "IMAGE": n_("Image"),
    "BRICK": n_("Brick"),
    "CHECKER": n_("Checker"),
    "GRADIENT": n_("Gradient"),
    "MAGIC": n_("Magic"),
    "MUSGRAVE": n_("Musgrave"),
    "NOISE": n_("Noise"),
    "VORONOI": n_("Voronoi"),
    "WAVE": n_("Wave"),
    "VCOL": n_("Vertex Color"),
    "BACKGROUND": n_("Background"),
    "COLOR": n_("Fill Layer"),
    "GROUP": n_("Group"),
    "HEMI": n_("Fake Lighting"),
    "GABOR": n_("Gabor"),
    "EDGE_DETECT": n_("Edge Detect"),
    "AO": n_("Ambient Occlusion"),
}

# Hemi space items
hemi_space_items = (
    ("WORLD", "World Space", ""),
    ("OBJECT", "Object Space", ""),
    ("CAMERA", "Camera Space", ""),
)

# Voronoi feature items
voronoi_feature_items = (
    (
        "F1",
        "F1",
        "Compute and return the distance to the closest feature point as well as its position and color",
    ),
    (
        "F2",
        "F2",
        "Compute and return the distance to the second closest feature point as well as its position and color.",
    ),
    ("SMOOTH_F1", "Smooth F1", "Compute and return a smooth version of F1."),
    (
        "DISTANCE_TO_EDGE",
        "Distance to Edge",
        "Compute and return the distance to the edges of the Voronoi cells.",
    ),
    (
        "N_SPHERE_RADIUS",
        "N-Sphere Radius",
        "Compute and return the radius of the n-sphere inscribed in the Voronoi cells. In other words, it is half the distance between the closest feature point and the feature point closest to it.",
    ),
)

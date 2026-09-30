# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mask-related constants for the paint module.

Contains constants for mask types, items, and labels.
"""

from mixar.modules.common.i18n import n_

# Mask type items
mask_type_items = (
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
    ("HEMI", "Fake Lighting", ""),
    ("OBJECT_INDEX", "Object Index", ""),
    ("COLOR_ID", "Color ID", ""),
    ("BACKFACE", "Backface", ""),
    ("EDGE_DETECT", "Edge Detect", ""),
    ("MODIFIER", "Modifier", ""),
    ("GABOR", "Gabor", ""),
    ("AO", "Ambient Occlusion", ""),
)

# Mask type labels
mask_type_labels = {
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
    "HEMI": n_("Fake Lighting"),
    "OBJECT_INDEX": n_("Object Index"),
    "COLOR_ID": n_("Color ID"),
    "BACKFACE": n_("Backface"),
    "EDGE_DETECT": n_("Edge Detect"),
    "MODIFIER": n_("Modifier"),
    "GABOR": n_("Gabor"),
    "AO": n_("Ambient Occlusion"),
}

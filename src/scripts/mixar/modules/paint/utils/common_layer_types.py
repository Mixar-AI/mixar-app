# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer type definitions and callbacks for the paint module."""

_base_layer_type_items = [
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
    ("PROCEDURAL", "Procedural Material", ""),
]

# This will be updated when procedural materials are loaded
_dynamic_layer_type_items = None


def get_layer_type_items_callback(self=None, context=None):
    """Callback function for EnumProperty items"""
    global _dynamic_layer_type_items

    # Return cached version if available
    if _dynamic_layer_type_items is not None:
        return _dynamic_layer_type_items

    # Otherwise return base items
    return _base_layer_type_items

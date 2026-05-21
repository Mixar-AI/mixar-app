# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from .constants import layer_type_labels


# Static blend type items tuple (for use with default= parameter)
BLEND_TYPE_ITEMS = (
    ("MIX", "Mix", ""),
    ("ADD", "Add", ""),
    ("SUBTRACT", "Subtract", ""),
    ("MULTIPLY", "Multiply", ""),
    ("SCREEN", "Screen", ""),
    ("OVERLAY", "Overlay", ""),
    ("DIFFERENCE", "Difference", ""),
    ("DIVIDE", "Divide", ""),
    ("DARKEN", "Darken", ""),
    ("LIGHTEN", "Lighten", ""),
    ("HUE", "Hue", ""),
    ("SATURATION", "Saturation", ""),
    ("VALUE", "Value", ""),
    ("COLOR", "Color", ""),
    ("SOFT_LIGHT", "Soft Light", ""),
    ("LINEAR_LIGHT", "Linear Light", ""),
    ("DODGE", "Dodge", ""),
    ("BURN", "Burn", ""),
    ("EXCLUSION", "Exclusion", ""),
)


def blend_type_items(self, context):
    """Returns a list of available blend mode types for layer blending.

    Provides standard blend modes used in image compositing operations,
    such as Mix, Add, Multiply, Screen, Overlay, etc.

    Parameters:
        self: The instance calling this method.
        context: The Blender context object.

    Returns:
        list: A list of tuples containing (identifier, label, description)
            for each available blend mode type.
    """
    items = [
        ("MIX", "Mix", ""),
        ("ADD", "Add", ""),
        ("SUBTRACT", "Subtract", ""),
        ("MULTIPLY", "Multiply", ""),
        ("SCREEN", "Screen", ""),
        ("OVERLAY", "Overlay", ""),
        ("DIFFERENCE", "Difference", ""),
        ("DIVIDE", "Divide", ""),
        ("DARKEN", "Darken", ""),
        ("LIGHTEN", "Lighten", ""),
        ("HUE", "Hue", ""),
        ("SATURATION", "Saturation", ""),
        ("VALUE", "Value", ""),
        ("COLOR", "Color", ""),
        ("SOFT_LIGHT", "Soft Light", ""),
        ("LINEAR_LIGHT", "Linear Light", ""),
        ("DODGE", "Dodge", ""),
        ("BURN", "Burn", ""),
        ("EXCLUSION", "Exclusion", ""),
    ]
    return items


def mask_blend_type_items(self, context):
    """Returns a list of available blend mode types for mask blending.

    Provides blend modes specifically for mask operations, similar to
    standard blend modes but with 'Replace' instead of 'Mix' for the
    MIX blend type.

    Parameters:
        self: The instance calling this method.
        context: The Blender context object.

    Returns:
        list: A list of tuples containing (identifier, label, description)
            for each available mask blend mode type.
    """
    items = [
        ("MIX", "Replace", ""),
        ("ADD", "Add", ""),
        ("SUBTRACT", "Subtract", ""),
        ("MULTIPLY", "Multiply", ""),
        ("SCREEN", "Screen", ""),
        ("OVERLAY", "Overlay", ""),
        ("DIFFERENCE", "Difference", ""),
        ("DIVIDE", "Divide", ""),
        ("DARKEN", "Darken", ""),
        ("LIGHTEN", "Lighten", ""),
        ("HUE", "Hue", ""),
        ("SATURATION", "Saturation", ""),
        ("VALUE", "Value", ""),
        ("COLOR", "Color", ""),
        ("SOFT_LIGHT", "Soft Light", ""),
        ("LINEAR_LIGHT", "Linear Light", ""),
        ("DODGE", "Dodge", ""),
        ("BURN", "Burn", ""),
        ("EXCLUSION", "Exclusion", ""),
    ]
    return items


def entity_input_items(self, context):
    """Returns a list of input channel items based on the entity/layer type.

    Examines the entity's path to determine if it's a layer channel, then
    generates appropriate input items (RGB, Alpha, etc.) based on the
    layer type (IMAGE, VCOL, VORONOI, GABOR, etc.). Different layer types
    provide different channel options.

    Parameters:
        self: The entity instance (layer or channel).
        context: The Blender context object.

    Returns:
        list: A list of tuples containing (identifier, label, description)
            for each available input channel based on the entity type.
    """
    mp = self.id_data.mp
    entity = self

    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", entity.path_from_id())
    if m:
        entity = mp.layers[int(m.group(1))]

    items = []

    if entity.type not in layer_type_labels:
        items.append(("RGB", "RGB", ""))
        items.append(("ALPHA", "Alpha", ""))
    else:
        label = layer_type_labels[entity.type]

        if entity.type == "VORONOI":
            items.append(("RGB", label + " Color", ""))
            items.append(("ALPHA", label + " Distance", ""))
        elif entity.type == "GABOR":
            items.append(("RGB", label + " Value", ""))
            items.append(("ALPHA", label + " Phase", ""))
        elif entity.type == "VCOL":
            items.append(("RGB", label, ""))
            items.append(("ALPHA", label + " Alpha", ""))
            items.append(("R", label + " Red", ""))
            items.append(("G", label + " Green", ""))
            items.append(("B", label + " Blue", ""))
        elif entity.type == "IMAGE":
            items.append(("RGB", label + " Color", ""))
            items.append(("ALPHA", label + " Alpha", ""))
        else:
            items.append(("RGB", label + " Color", ""))
            items.append(("ALPHA", label + " Factor", ""))

    return items


def get_layer_type_icon(layer_type):
    """Returns the appropriate Blender icon identifier for a given layer type.

    Maps layer type strings to their corresponding Blender UI icon identifiers
    for visual representation in the interface.

    Parameters:
        layer_type (str): The type of layer (e.g., "IMAGE", "VCOL", "BACKGROUND",
            "GROUP", "COLOR", "HEMI").

    Returns:
        str: The Blender icon identifier string. Returns "TEXTURE" as the default
            icon if the layer type doesn't match any specific type.
    """

    if layer_type == "IMAGE":
        return "IMAGE_DATA"
    elif layer_type == "VCOL":
        return "GROUP_VCOL"
    elif layer_type == "BACKGROUND":
        return "IMAGE_RGB_ALPHA"
    elif layer_type == "GROUP":
        return "FILE_FOLDER"
    elif layer_type == "COLOR":
        return "COLOR"
    elif layer_type == "HEMI":
        return "LIGHT"

    return "TEXTURE"

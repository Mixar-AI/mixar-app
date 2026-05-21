# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image format helper functions.

This module provides functions for handling image file format selections,
color mode and depth items for UI enum properties.
"""


def color_mode_items(self, context):
    """Generate color mode items based on the selected file format.

    Provides available color mode options (BW, RGB, RGBA) depending on which
    file format is currently selected.

    Args:
        self: The operator instance containing file_format property.
        context: The Blender context.

    Returns:
        List of tuples containing color mode enum items (identifier, name, description).
    """
    items = []

    if self.file_format in {"BMP", "IRIS", "PNG", "JPEG", "TARGA", "TARGA_RAW", "TIFF"}:
        items.append(("BW", "BW", ""))

    items.append(("RGB", "RGB", ""))

    if self.file_format not in {"BMP", "JPEG", "CINEON", "HDR"}:
        items.append(("RGBA", "RGBA", ""))

    return items


def color_depth_items(self, context):
    """Generate color depth items based on the selected file format.

    Provides available bit depth options appropriate for the currently selected
    file format (e.g., 8/16 for PNG, Float Half/Full for EXR).

    Args:
        self: The operator instance containing file_format property.
        context: The Blender context.

    Returns:
        Tuple of tuples containing color depth enum items (identifier, name, description).
    """
    if self.file_format in {"PNG", "TIFF"}:
        items = (("8", "8", ""), ("16", "16", ""))
    elif self.file_format in {"JPEG2000"}:
        items = (("8", "8", ""), ("12", "12", ""), ("16", "16", ""))
    elif self.file_format in {"DPX"}:
        items = (("8", "8", ""), ("10", "10", ""), ("12", "12", ""), ("16", "16", ""))
    elif self.file_format in {"OPEN_EXR_MULTILAYER", "OPEN_EXR"}:
        items = (("16", "Float (Half)", ""), ("32", "Float (Full)", ""))
    else:
        items = (
            ("8", "8", ""),
            ("10", "10", ""),
            ("12", "12", ""),
            ("16", "16", ""),
            ("32", "32", ""),
        )

    return items


def update_save_as_file_format(self, context):
    """Update color mode and depth settings when file format changes.

    Automatically adjusts color mode (RGB/RGBA) and color depth based on the newly
    selected file format and whether the image is float.

    Args:
        self: The operator instance containing format and image properties.
        context: The Blender context.

    Returns:
        None
    """
    if self.file_format in {"BMP", "JPEG", "CINEON", "HDR"}:
        self.color_mode = "RGB"
    else:
        self.color_mode = "RGBA"

    if self.file_format in {
        "BMP",
        "IRIS",
        "PNG",
        "JPEG",
        "JPEG2000",
        "TARGA",
        "TARGA_RAW",
        "WEBP",
    }:
        self.color_depth = "8"
    elif self.file_format in {"CINEON", "DPX"}:
        self.color_depth = "10"
    elif self.file_format in {"TIFF"}:
        self.color_depth = "16"
    elif self.file_format in {"HDR", "OPEN_EXR_MULTILAYER", "OPEN_EXR"}:
        self.color_depth = "32"

    if self.is_float and self.file_format in {"PNG", "JPEG2000"}:
        self.color_depth = "16"


def get_file_format_items():
    """Get the list of available image file format items for UI enum properties.

    Builds a list of supported image file formats including BMP, PNG, JPEG, EXR, TIFF,
    WebP, and others with their display names and icons.

    Args:
        None

    Returns:
        List of tuples containing file format enum items (identifier, name, description, icon, index).
    """
    items = [
        ("BMP", "BMP", "", "IMAGE_DATA", 0),
        ("IRIS", "Iris", "", "IMAGE_DATA", 1),
        ("PNG", "PNG", "", "IMAGE_DATA", 2),
        ("JPEG", "JPEG", "", "IMAGE_DATA", 3),
        ("JPEG2000", "JPEG 2000", "", "IMAGE_DATA", 4),
        ("TARGA", "Targa", "", "IMAGE_DATA", 5),
        ("TARGA_RAW", "Targa Raw", "", "IMAGE_DATA", 6),
        ("CINEON", "Cineon", "", "IMAGE_DATA", 7),
        ("DPX", "DPX", "", "IMAGE_DATA", 8),
        ("OPEN_EXR_MULTILAYER", "OpenEXR Multilayer", "", "IMAGE_DATA", 9),
        ("OPEN_EXR", "OpenEXR", "", "IMAGE_DATA", 10),
        ("HDR", "Radiance HDR", "", "IMAGE_DATA", 11),
        ("TIFF", "TIFF", "", "IMAGE_DATA", 12),
    ]

    items.append(("WEBP", "WebP", "", "IMAGE_DATA", 13))

    return items

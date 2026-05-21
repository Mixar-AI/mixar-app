# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing helper functions for Save As Image operator.

This module provides helper functions for drawing the UI elements
of the MSaveAsImage operator panel.
"""


def draw_labeled_row(col, label_text, scale_y=1.4, split_factor=0.25):
    """Create a labeled row with standard layout.

    Args:
        col: The column layout to add the row to.
        label_text: The label text to display.
        scale_y: The vertical scale of the row. Defaults to 1.4.
        split_factor: The split factor for label/content. Defaults to 0.25.

    Returns:
        Tuple of (row, label_col, content_split) for further customization.
    """
    row = col.row(align=True)
    row.scale_y = scale_y
    split = row.split(factor=split_factor, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text=label_text)
    return row, label_col, split


def draw_file_format_section(layout, operator):
    """Draw the file format section of the Save As panel.

    Args:
        layout: The Blender layout to draw in.
        operator: The MSaveAsImage operator instance.

    Returns:
        None
    """
    main_col = layout.column(align=False)

    # ========== FILE FORMAT ==========
    box = main_col.box()
    col = box.column(align=False)

    # Header
    header_row = col.row(align=True)
    header_row.scale_y = 1.4
    header_row.label(text="File Format", icon="IMAGE_DATA")

    col.separator(factor=1.2)

    # File Format
    _, _, split = draw_labeled_row(col, "Format:")
    split.prop(operator, "file_format", text="")

    col.separator(factor=0.4)

    # Color Mode
    _, _, split = draw_labeled_row(col, "Color Mode:")
    row_inner = split.row(align=True)
    row_inner.prop(operator, "color_mode", expand=True)

    # Color Depth (for specific formats)
    if operator.file_format in {
        "PNG",
        "JPEG2000",
        "DPX",
        "OPEN_EXR_MULTILAYER",
        "OPEN_EXR",
        "TIFF",
    }:
        col.separator(factor=0.4)
        _, _, split = draw_labeled_row(col, "Color Depth:")
        row_inner = split.row(align=True)
        row_inner.prop(operator, "color_depth", expand=True)

    # Draw format-specific options
    _draw_format_specific_options(col, operator)

    col.separator(factor=0.8)
    return main_col


def _draw_format_specific_options(col, operator):
    """Draw format-specific options based on selected file format.

    Args:
        col: The column layout to add options to.
        operator: The MSaveAsImage operator instance.

    Returns:
        None
    """
    file_format = operator.file_format

    # PNG Compression
    if file_format == "PNG":
        col.separator(factor=0.4)
        _, _, split = draw_labeled_row(col, "Compression:")
        split.prop(operator, "compression", text="")

    # Quality (JPEG, JPEG2000, WEBP)
    if file_format in {"JPEG", "JPEG2000", "WEBP"}:
        col.separator(factor=0.4)
        _, _, split = draw_labeled_row(col, "Quality:")
        split.prop(operator, "quality", text="")

    # TIFF Codec
    if file_format == "TIFF":
        col.separator(factor=0.4)
        _, _, split = draw_labeled_row(col, "Compression:")
        split.prop(operator, "tiff_codec", text="")

    # EXR Codec
    if file_format in {"OPEN_EXR", "OPEN_EXR_MULTILAYER"}:
        col.separator(factor=0.4)
        _, _, split = draw_labeled_row(col, "Codec:")
        split.prop(operator, "exr_codec", text="")

    # EXR Z Buffer
    if file_format == "OPEN_EXR":
        col.separator(factor=0.4)
        _, _, split = draw_labeled_row(col, "Z Buffer:", scale_y=1.2)
        split.prop(operator, "use_zbuffer", text="")

    # Cineon
    if file_format == "CINEON":
        col.separator(factor=0.4)
        row = col.row(align=True)
        row.label(text="Hard coded Non-Linear, Gamma:1.7")

    # JPEG2000 specific options
    if file_format == "JPEG2000":
        _draw_jpeg2000_options(col, operator)

    # DPX Log
    if file_format == "DPX":
        col.separator(factor=0.4)
        _, _, split = draw_labeled_row(col, "Log:", scale_y=1.2)
        split.prop(operator, "use_cineon_log", text="")


def _draw_jpeg2000_options(col, operator):
    """Draw JPEG2000-specific options.

    Args:
        col: The column layout to add options to.
        operator: The MSaveAsImage operator instance.

    Returns:
        None
    """
    col.separator(factor=0.4)
    _, _, split = draw_labeled_row(col, "Codec:")
    split.prop(operator, "jpeg2k_codec", text="")

    col.separator(factor=0.4)
    _, _, split = draw_labeled_row(col, "Cinema 48:", scale_y=1.2)
    split.prop(operator, "use_jpeg2k_cinema_48", text="")

    col.separator(factor=0.4)
    _, _, split = draw_labeled_row(col, "Cinema:", scale_y=1.2)
    split.prop(operator, "use_jpeg2k_cinema_preset", text="")

    col.separator(factor=0.4)
    _, _, split = draw_labeled_row(col, "YCC:", scale_y=1.2)
    split.prop(operator, "use_jpeg2k_ycc", text="")


def draw_save_options_section(layout, operator):
    """Draw the save options section of the Save As panel.

    Args:
        layout: The Blender layout (typically main_col from file format section).
        operator: The MSaveAsImage operator instance.

    Returns:
        None
    """
    layout.separator(factor=0.8)

    # ========== SAVE OPTIONS ==========
    box = layout.box()
    col = box.column(align=False)

    # Header
    header_row = col.row(align=True)
    header_row.scale_y = 1.4
    header_row.label(text="Save Options", icon="FILE_IMAGE")

    col.separator(factor=1.2)

    # Copy
    _, _, split = draw_labeled_row(col, "Copy:", scale_y=1.2)
    split.prop(operator, "copy", text="")

    if not operator.copy:
        col.separator(factor=0.4)

        # Relative Path
        _, _, split = draw_labeled_row(col, "Relative Path:", scale_y=1.2)
        split.prop(operator, "relative", text="")

    col.separator(factor=0.8)
    layout.separator(factor=0.8)


def draw_save_as_panel(layout, operator):
    """Draw the complete Save As Image panel.

    This is the main entry point for drawing the Save As panel UI.

    Args:
        layout: The Blender layout to draw in.
        operator: The MSaveAsImage operator instance.

    Returns:
        None
    """
    layout.use_property_split = False
    layout.use_property_decorate = False

    main_col = draw_file_format_section(layout, operator)
    draw_save_options_section(main_col, operator)

# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing methods for MBakeEntityToImage operator."""


def _draw_row(col, label, scale_y=1.4, split_factor=0.25):
    """Create a standard row with label column and return split for content.

    Args:
        col: Parent column layout
        label: Text label for the row
        scale_y: Vertical scale factor (default 1.4)
        split_factor: Split factor for label/content (default 0.25)

    Returns:
        Tuple of (row, split) for further customization
    """
    row = col.row(align=True)
    row.scale_y = scale_y
    split = row.split(factor=split_factor, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text=label)
    return row, split


def draw_bake_entity_to_image_ui(operator, context):
    """Draw the bake entity to image operator UI.

    Args:
        operator: The MBakeEntityToImage operator instance
        context: Blender context
    """
    layout = operator.layout
    layout.use_property_split = False
    layout.use_property_decorate = False

    main_col = layout.column(align=False)

    # ========== BAKE TO IMAGE ==========
    box = main_col.box()
    col = box.column(align=False)

    # Header
    header_row = col.row(align=True)
    header_row.scale_y = 1.4
    header_row.label(text="Bake to Image", icon="RENDER_STILL")

    col.separator(factor=1.2)

    # Name
    _draw_name_section(operator, col)

    # Image settings (HDR, resolution)
    _draw_image_settings(operator, col)

    # Sampling and UV settings
    _draw_sampling_uv_settings(operator, col)

    # Processing options (blur, FXAA, denoise)
    _draw_processing_options(operator, col)

    # Entity-specific options (duplicate, disable)
    _draw_entity_options(operator, col)

    # Image atlas option
    _draw_image_atlas_option(operator, col)

    col.separator(factor=0.8)
    main_col.separator(factor=0.8)


def _draw_name_section(operator, col):
    """Draw the name input section.

    Args:
        operator: The MBakeEntityToImage operator instance
        col: Column layout
    """
    _, split = _draw_row(col, "Name:")
    split.prop(operator, "name", text="")
    col.separator(factor=0.4)


def _draw_image_settings(operator, col):
    """Draw image settings section (HDR, resolution).

    Args:
        operator: The MBakeEntityToImage operator instance
        col: Column layout
    """
    # HDR
    _, split = _draw_row(col, "32-bit Float:", scale_y=1.2)
    split.prop(operator, "hdr", text="")
    col.separator(factor=0.4)

    # Custom Resolution
    _, split = _draw_row(col, "Custom Res:", scale_y=1.2)
    split.prop(operator, "use_custom_resolution", text="")
    col.separator(factor=0.4)

    if not operator.use_custom_resolution:
        _, split = _draw_row(col, "Resolution:")
        crow = split.row(align=True)
        crow.prop(operator, "image_resolution", expand=True)
        col.separator(factor=0.4)
    else:
        _, split = _draw_row(col, "Width:")
        split.prop(operator, "width", text="")
        col.separator(factor=0.4)

        _, split = _draw_row(col, "Height:")
        split.prop(operator, "height", text="")
        col.separator(factor=0.4)


def _draw_sampling_uv_settings(operator, col):
    """Draw sampling and UV settings section.

    Args:
        operator: The MBakeEntityToImage operator instance
        col: Column layout
    """
    # Samples
    _, split = _draw_row(col, "Samples:")
    split.prop(operator, "samples", text="")
    col.separator(factor=0.4)

    # UV Map
    _, split = _draw_row(col, "UV Map:")
    split.prop_search(operator, "uv_map", operator, "uv_map_coll", text="", icon="GROUP_UVS")
    col.separator(factor=0.4)

    # Margin
    _, split = _draw_row(col, "Margin:")
    margin_split = split.split(factor=0.4, align=True)
    margin_split.prop(operator, "margin", text="")
    margin_split.prop(operator, "margin_type", text="")
    col.separator(factor=0.4)

    # Bake Device
    _, split = _draw_row(col, "Device:")
    split.prop(operator, "bake_device", text="")
    col.separator(factor=0.4)


def _draw_processing_options(operator, col):
    """Draw processing options section (blur, FXAA, denoise).

    Args:
        operator: The MBakeEntityToImage operator instance
        col: Column layout
    """
    # Blur
    _, split = _draw_row(col, "Use Blur:", scale_y=1.2)
    rrow = split.row(align=True)
    rrow.prop(operator, "blur", text="")
    if operator.blur:
        rrow.prop(operator, "blur_type", text="")
    col.separator(factor=0.4)

    if operator.blur:
        _, split = _draw_row(col, "Blur Factor:" if operator.blur_type == "NOISE" else "Blur Size:")
        if operator.blur_type == "NOISE":
            split.prop(operator, "blur_factor", text="")
        else:
            split.prop(operator, "blur_size", text="")
        col.separator(factor=0.4)

    # FXAA
    _, split = _draw_row(col, "Use FXAA:", scale_y=1.2)
    split.prop(operator, "fxaa", text="")
    col.separator(factor=0.4)

    # Denoise
    _, split = _draw_row(col, "Use Denoise:", scale_y=1.2)
    split.prop(operator, "denoise", text="")
    col.separator(factor=0.4)


def _draw_entity_options(operator, col):
    """Draw entity-specific options (duplicate, disable).

    Args:
        operator: The MBakeEntityToImage operator instance
        col: Column layout
    """
    # Duplicate Entity - only for masks
    if operator.mask:
        _, split = _draw_row(col, "Duplicate:", scale_y=1.2)
        split.prop(operator, "duplicate_entity", text="Duplicate Mask")
        col.separator(factor=0.4)

        if operator.duplicate_entity:
            _, split = _draw_row(col, "Disable Current:", scale_y=1.2)
            split.prop(operator, "disable_current", text="Disable Current Mask")
            col.separator(factor=0.4)
    elif operator.duplicate_entity:
        _, split = _draw_row(col, "Disable Current:", scale_y=1.2)
        split.prop(operator, "disable_current", text="Disable Current Layer")
        col.separator(factor=0.4)


def _draw_image_atlas_option(operator, col):
    """Draw image atlas option.

    Args:
        operator: The MBakeEntityToImage operator instance
        col: Column layout
    """
    _, split = _draw_row(col, "Image Atlas:", scale_y=1.2)
    split.prop(operator, "use_image_atlas", text="")
    col.separator(factor=0.4)

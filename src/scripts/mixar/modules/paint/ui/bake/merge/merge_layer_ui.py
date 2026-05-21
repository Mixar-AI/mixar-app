# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing logic for merge layer operator"""


def draw_merge_layer_dialog(operator, context):
    """
    Draw the merge layer dialog UI.

    Args:
        operator: The merge layer operator instance
        context: The Blender context
    """
    layout = operator.layout
    layout.use_property_split = False
    layout.use_property_decorate = False

    main_ch = operator.mp.channels[int(operator.channel_idx)]
    ch = operator.layer.channels[int(operator.channel_idx)]
    blend_type = ch.blend_type if main_ch.type != "NORMAL" else ch.normal_blend_type

    main_col = layout.column(align=False)

    # Draw main settings box
    _draw_settings_box(operator, main_col, blend_type)

    main_col.separator(factor=0.8)

    # Draw dirty images warning if needed
    if operator.any_dirty_images:
        _draw_dirty_images_warning(layout)


def _draw_settings_box(operator, main_col, blend_type):
    """
    Draw the main settings box.

    Args:
        operator: The merge layer operator instance
        main_col: The main column layout
        blend_type: The current blend type
    """
    box = main_col.box()
    col = box.column(align=False)

    # Header
    header_row = col.row(align=True)
    header_row.scale_y = 1.4
    header_row.label(text="Merge Layer Settings", icon="RENDERLAYERS")

    col.separator(factor=1.2)

    # Main Channel
    _draw_property_row(col, "Main Channel:", operator, "channel_idx", scale_y=1.4)
    col.separator(factor=0.4)

    # Apply Modifiers
    _draw_property_row(col, "Apply Mods:", operator, "apply_modifiers", scale_y=1.2)
    col.separator(factor=0.4)

    # Apply Neighbor Modifiers
    _draw_property_row(
        col, "Neighbor Mods:", operator, "apply_neighbor_modifiers", scale_y=1.2
    )
    col.separator(factor=0.4)

    if blend_type != "MIX":
        # Force Mix Blending
        _draw_property_row(
            col, "Force Mix:", operator, "force_mix_blending", scale_y=1.2
        )
        col.separator(factor=0.4)

    col.separator(factor=0.8)


def _draw_property_row(col, label, operator, prop_name, scale_y=1.0):
    """
    Draw a property row with label and value.

    Args:
        col: The column layout
        label: The label text
        operator: The operator instance
        prop_name: The property name to draw
        scale_y: The vertical scale factor
    """
    row = col.row(align=True)
    row.scale_y = scale_y
    split = row.split(factor=0.25, align=True)
    label_col = split.column(align=True)
    label_col.alignment = "RIGHT"
    label_col.label(text=label)
    split.prop(operator, prop_name, text="")


def _draw_dirty_images_warning(layout):
    """
    Draw the warning for unsaved images.

    Args:
        layout: The layout to draw in
    """
    col = layout.column(align=True)
    col.label(
        text="Unsaved data will be LOST if you UNDO this operation.",
        icon="ERROR",
    )
    col.label(text="Are you sure you want to continue?", icon="BLANK1")

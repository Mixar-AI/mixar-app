# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drawing functions for the Export Textures section of the baking panel.

Contains all UI drawing logic for custom bake targets, channel configuration,
and batch export actions in the TEXTURE_EXPORT tab.
"""

import bpy

from ...utils.common_ui import split_layout


# Channel display configuration
_CHANNEL_LETTERS = ('r', 'g', 'b', 'a')
_CHANNEL_ICONS = {
    'r': 'EVENT_R',
    'g': 'EVENT_G',
    'b': 'EVENT_B',
    'a': 'EVENT_A',
}
_CHANNEL_LABELS = {'r': 'R', 'g': 'G', 'b': 'B', 'a': 'A'}


def draw_export_textures_section(layout, mp, node):
    """Draw the full Export Textures section.

    This is the main entry point called from baking_panel.py's TEXTURE_EXPORT tab.

    Args:
        layout: Blender UI layout.
        mp: MPaint property group.
        node: The active Mixar paint node.
    """
    # Section 1: Custom Bake Targets list
    _draw_bake_targets_list(layout, mp)

    # Section 2: Active bake target details (if one is selected)
    if (len(mp.bake_targets) > 0
            and 0 <= mp.active_bake_target_index < len(mp.bake_targets)):
        _draw_bake_target_details(layout, mp, node)

    layout.separator()

    # Section 3: Export actions
    _draw_export_actions(layout, mp, node)


def _draw_bake_targets_list(layout, mp):
    """Draw the bake targets UIList with sidebar action buttons.

    Args:
        layout: Blender UI layout.
        mp: MPaint property group.
    """
    box = layout.box()
    box.label(text="Custom Bake Targets", icon='EXPORT')

    row = box.row()

    # UIList (left side, takes most space)
    row.template_list(
        "BAKE_UL_bake_target_list",
        "",
        mp,
        "bake_targets",
        mp,
        "active_bake_target_index",
        rows=3,
        maxrows=5,
    )

    # Sidebar buttons (right side, vertical column)
    col = row.column(align=True)
    col.operator("wm.m_new_bake_target", text="", icon='ADD')
    col.operator("wm.m_remove_bake_target", text="", icon='REMOVE')
    col.separator()
    col.menu("BAKE_MT_bake_target_special_menu", text="", icon='DOWNARROW_HLT')


def _draw_bake_target_details(layout, mp, node):
    """Draw expanded details for the active bake target.

    Shows a collapsible section with RGBA channel configuration and image info.

    Args:
        layout: Blender UI layout.
        mp: MPaint property group.
        node: The active Mixar paint node.
    """
    tree = node.node_tree
    bt = mp.bake_targets[mp.active_bake_target_index]
    wm = bpy.context.window_manager
    btui = wm.mpui.bake_target_ui

    box = layout.box()

    # Header row with collapse toggle + bake target name
    header = box.row(align=True)
    expand_icon = 'TRIA_DOWN' if btui.expand_content else 'TRIA_RIGHT'
    header.prop(btui, "expand_content", text="", icon=expand_icon, emboss=False)

    # Show image name if baked, else bake target name
    bt_node = tree.nodes.get(bt.image_node)
    has_image = bt_node and bt_node.image

    if has_image:
        bt_label = bt_node.image.name
        if bt_node.image.is_float:
            bt_label += " (Float)"
        header.prop(
            btui, "expand_content", text=bt_label,
            emboss=False, icon='IMAGE_DATA'
        )
    else:
        bt_label = bt.name
        if bt.use_float:
            bt_label += " (Float)"
        header.prop(
            btui, "expand_content", text=bt_label,
            emboss=False, icon='RENDER_STILL'
        )

    # Only draw content if expanded
    if not btui.expand_content:
        return

    col = box.column(align=True)
    col.separator(factor=0.5)

    # RGBA channel rows
    for letter in _CHANNEL_LETTERS:
        _draw_bake_target_channel(col, bt, letter, mp, btui)
        col.separator(factor=0.3)

    col.separator(factor=0.5)

    # Image info row
    info_row = col.row(align=True)
    info_row.label(text="", icon='BLANK1')
    if has_image:
        img = bt_node.image
        info_row.label(
            text=f"Image: {img.name}", icon='IMAGE_DATA'
        )
    else:
        info_row.label(
            text="Bake All Channels to get the image!",
            icon='ERROR'
        )


def _draw_bake_target_channel(layout, bt, letter, mp, btui):
    """Draw a single RGBA channel row for a bake target.

    Shows channel source assignment, subchannel selector, default value,
    and optionally normal type and invert toggle when expanded.

    Args:
        layout: Blender UI layout (column).
        bt: MBakeTarget PropertyGroup.
        letter: Channel letter ('r', 'g', 'b', or 'a').
        mp: MPaint property group (for channel collection).
        btui: MBakeTargetUI PropertyGroup (for expand states).
    """
    btc = getattr(bt, letter)  # MBakeTargetChannel
    expand_prop = f"expand_{letter}"
    is_expanded = getattr(btui, expand_prop)

    # Find the source channel if assigned
    source_ch = None
    if btc.channel_name:
        for ch in mp.channels:
            if ch.name == btc.channel_name:
                source_ch = ch
                break

    # Main channel row
    row = layout.row(align=True)

    if source_ch:
        # Has a source channel — show expand arrow + channel icon
        expand_icon = 'TRIA_DOWN' if is_expanded else 'TRIA_RIGHT'
        row.prop(btui, expand_prop, text="", icon=expand_icon, emboss=False)

        ch_icon = _CHANNEL_ICONS.get(letter, 'DOT')
        row.prop(btui, expand_prop, text="", icon=ch_icon, emboss=False)
    else:
        # No source channel — just show icon
        row.label(text="", icon='BLANK1')
        ch_icon = _CHANNEL_ICONS.get(letter, 'DOT')
        row.label(text="", icon=ch_icon)

    # Channel source search + subchannel/default_value
    if not btc.channel_name:
        # No channel assigned: show search (65%) + default value (35%)
        split = split_layout(row, 0.65, align=True)
        split.prop_search(btc, "channel_name", mp, "channels", text="")
        split.prop(btc, "default_value", text="")
    elif source_ch and source_ch.type in ('RGB', 'NORMAL'):
        # RGB/NORMAL: show search (75%) + subchannel selector (25%)
        if source_ch.type == 'NORMAL' and btc.normal_type == 'DISPLACEMENT':
            # Displacement has no subchannel
            row.prop_search(btc, "channel_name", mp, "channels", text="")
        else:
            split = split_layout(row, 0.75, align=True)
            split.prop_search(btc, "channel_name", mp, "channels", text="")
            split.prop(btc, "subchannel_index", text="")
    else:
        # VALUE channel: just search, full width
        row.prop_search(btc, "channel_name", mp, "channels", text="")

    # Expanded details
    if source_ch and is_expanded:
        detail_row = layout.row(align=True)
        detail_row.label(text="", icon='BLANK1')
        detail_box = detail_row.box()
        detail_col = detail_box.column()

        # Normal type selector (only for NORMAL channels)
        if source_ch.type == 'NORMAL':
            brow = split_layout(detail_col, 0.3, align=True)
            brow.label(text="Source:")
            brow.prop(btc, "normal_type", text="")

        # Invert value toggle
        brow = detail_col.row(align=True)
        brow.label(text="Invert Value:")
        brow.prop(btc, "invert_value", text="")


def _draw_export_actions(layout, mp, node):
    """Draw the export/save/delete action buttons.

    Args:
        layout: Blender UI layout.
        mp: MPaint property group.
        node: The active Mixar paint node.
    """
    tree = node.node_tree

    # Check if any baked content exists (channels or bake targets with images)
    has_baked_channels = False
    for ch in mp.channels:
        baked_node = tree.nodes.get(ch.baked)
        if baked_node and baked_node.image:
            has_baked_channels = True
            break

    has_baked_targets = False
    for bt in mp.bake_targets:
        bt_node = tree.nodes.get(bt.image_node)
        if bt_node and bt_node.image:
            has_baked_targets = True
            break

    has_any_baked = has_baked_channels or has_baked_targets

    box = layout.box()
    box.label(text="Export Textures", icon='EXPORT')

    col = box.column(align=True)

    if not has_any_baked:
        col.label(text="Bake channels first to export", icon='INFO')
        return

    # Save As All button
    row = col.row(align=True)
    row.scale_y = 1.3
    op = row.operator(
        "wm.m_save_all_baked_images",
        text="Save As All...",
        icon='FILE_TICK'
    )
    op.copy = False

    # Save Copies All button
    op = row.operator(
        "wm.m_save_all_baked_images",
        text="Save Copies All...",
        icon='FILE_TICK'
    )
    op.copy = True

    col.separator(factor=0.5)

    # Delete All Baked button
    row = col.row(align=True)
    row.scale_y = 1.1
    row.operator(
        "wm.m_delete_baked_channel_images",
        text="Delete All Baked",
        icon='TRASH'
    )

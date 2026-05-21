# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel section UI drawing helpers for Texture Sets panel.

This module provides functions to draw the channels management UI including:
- Collapsible channels section header
- Channel UIList with add/remove/move buttons
- Channel settings panel for the selected channel
"""

from ...core.node.node_utils import get_active_mpaint_node
from ...core.lib.lib import channel_custom_icon_dict
from ...core.lib.lib_operations import get_icon


def draw_channels_section(context, layout):
    """Draw the channels UI section with list and settings.

    Displays a collapsible channels section containing:
    - Preview mode toggle
    - Channel UIList
    - Add/Remove/Move buttons
    - Channel settings panel (when channel is selected)

    Args:
        context: Blender context.
        layout: UI layout to draw into.
    """
    node = get_active_mpaint_node()
    if not node or not node.node_tree:
        return

    mp = node.node_tree.mp
    wm = context.window_manager
    if not hasattr(wm, 'mpui'):
        return
    mpui = wm.mpui

    # ========== CHANNELS HEADER ==========
    row = layout.row(align=True)
    icon = 'TRIA_DOWN' if mpui.show_channels else 'TRIA_RIGHT'

    rrow = row.row(align=True)
    rrow.alignment = 'LEFT'
    rrow.scale_x = 0.95

    channel_count = len(mp.channels)
    rrow.prop(mpui, 'show_channels', emboss=False,
              text=f'Channels ({channel_count})', icon=icon)

    # ========== CHANNELS LIST (EXPANDED STATE) ==========
    if not mpui.show_channels:
        return

    box = layout.box()
    col = box.column()

    # Preview mode toggle (only if channels exist)
    if channel_count > 0 and hasattr(mp, 'preview_mode'):
        preview_row = col.row()
        if mp.preview_mode:
            preview_row.alert = True
        preview_row.prop(mp, 'preview_mode', text='Preview Mode', icon='HIDE_OFF')
        col.separator(factor=0.5)

    # Channel list with buttons
    row = col.row()

    # UIList
    row.template_list(
        "CHANNELS_UL_channel_list", "",
        mp, "channels",
        mp, "active_channel_index",
        rows=3, maxrows=5
    )

    # Buttons column
    col_buttons = row.column(align=True)
    col_buttons.menu("CHANNELS_MT_add_channel_menu", text="", icon='ADD')
    col_buttons.operator("channels.remove_channel", text="", icon='REMOVE')
    col_buttons.separator()
    col_buttons.operator("channels.move_channel", text="", icon='TRIA_UP').direction = 'UP'
    col_buttons.operator("channels.move_channel", text="", icon='TRIA_DOWN').direction = 'DOWN'

    # Channel settings panel (if channel selected)
    if channel_count > 0:
        col.separator(factor=0.5)
        _draw_channel_settings_panel(col, mp, mpui, node)


def _draw_channel_settings_panel(layout, mp, mpui, node):
    """Draw settings panel for the selected channel.

    Args:
        layout: UI layout to draw into.
        mp: MPaint property group.
        mpui: MPaintUI property group.
        node: Active MPaint node.
    """
    if mp.active_channel_index < 0 or mp.active_channel_index >= len(mp.channels):
        return

    channel = mp.channels[mp.active_channel_index]

    # Collapsible settings header
    mcol = layout.column(align=False)
    row = mcol.row(align=True)

    rrow = row.row(align=True)
    rrow.alignment = 'LEFT'
    rrow.scale_x = 0.95

    # Use channel's own expand property if available
    expand_prop = 'expand_content'
    is_expanded = getattr(channel, expand_prop, False) if hasattr(channel, expand_prop) else False

    icon = 'TRIA_DOWN' if is_expanded else 'TRIA_RIGHT'

    # Channel type icon - try custom icons first
    icon_name = channel_custom_icon_dict.get(channel.type, 'rgb_channel')
    icon_value = get_icon(icon_name)

    rrow.prop(channel, expand_prop, text='', emboss=False, icon=icon)

    if icon_value:
        rrow.prop(channel, expand_prop, text=f'{channel.name} Channel',
                  emboss=False, icon_value=icon_value)
    else:
        # Fallback to standard icons
        fallback_icons = {'VALUE': 'SHADING_TEXTURE', 'RGB': 'COLOR', 'NORMAL': 'NORMALS_FACE'}
        type_icon = fallback_icons.get(channel.type, 'DOT')
        rrow.prop(channel, expand_prop, text=f'{channel.name} Channel',
                  emboss=False, icon=type_icon)

    # Settings menu button on the right (if menu exists)
    # rrow = row.row(align=True)
    # rrow.alignment = 'RIGHT'
    # rrow.menu("CHANNELS_MT_channel_special_menu", icon='PREFERENCES', text='')

    if not is_expanded:
        return

    # Settings content in a box
    row = mcol.row(align=True)
    row.label(text='', icon='BLANK1')
    box = row.box()
    bcol = box.column()

    _draw_channel_settings_content(bcol, channel, node, mp)


def _draw_channel_settings_content(layout, channel, node, mp):
    """Draw the actual channel settings controls matching ucupaint style.

    Args:
        layout: UI layout to draw into.
        channel: MPaintChannel to configure.
        node: Active MPaint node.
        mp: MPaint property group.
    """
    # Get the input socket for this channel
    io_index = channel.io_index
    inp = node.inputs[io_index] if 0 <= io_index < len(node.inputs) else None

    # ========== BACKGROUND / BASE VALUE ==========
    if channel.type in {'RGB', 'VALUE'}:
        brow = layout.row(align=True)
        brow.label(text='', icon='BLANK1')

        if channel.type == 'RGB':
            brow.label(text='Background:')
        elif channel.type == 'VALUE':
            brow.label(text='Base Value:')

        if inp:
            if len(inp.links) == 0:
                brow.prop(inp, 'default_value', text='')
            else:
                brow.label(text='', icon='LINKED')

    # ========== ALPHA SETTINGS (RGB only) ==========
    if channel.type == 'RGB':
        _draw_alpha_settings(layout, channel, node, mp)

    # ========== USE CLAMP ==========
    if channel.type in {'RGB', 'VALUE'}:
        brow = layout.row(align=True)
        brow.label(text='', icon='BLANK1')
        brow.label(text='Use Clamp:')
        brow.prop(channel, 'use_clamp', text='')

    # ========== COLORSPACE ==========
    if channel.type in {'RGB', 'VALUE'} and hasattr(channel, 'colorspace'):
        brow = layout.row(align=True)
        brow.label(text='', icon='BLANK1')
        brow.label(text='Colorspace:')
        brow.prop(channel, 'colorspace', text='')

    # ========== NORMAL CHANNEL SETTINGS ==========
    if channel.type == 'NORMAL':
        _draw_normal_settings(layout, channel)


def _draw_alpha_settings(layout, channel, node, mp):
    """Draw alpha settings for RGB channels matching ucupaint style.

    Args:
        layout: UI layout to draw into.
        channel: MPaintChannel to configure.
        node: Active MPaint node.
        mp: MPaint property group.
    """
    # Check if another channel already has alpha enabled
    other_has_alpha = any(c.enable_alpha for c in mp.channels if c != channel and hasattr(c, 'enable_alpha'))

    # Only show alpha settings if no other channel has alpha, or this channel has it
    if other_has_alpha and not channel.enable_alpha:
        return

    brow = layout.row(align=True)

    # Alpha toggle row
    rrow = brow.row(align=True)

    # Show expand button if we have settings to show
    expand_prop = 'expand_alpha_settings'
    is_expanded = getattr(channel, expand_prop, False) if hasattr(channel, expand_prop) else False

    if channel.enable_alpha and not is_expanded:
        # Show "Base Alpha:" with value picker when enabled but not expanded
        icon = 'TRIA_DOWN' if is_expanded else 'TRIA_RIGHT'
        rrow.prop(channel, expand_prop, text='', emboss=False, icon=icon)
        rrow.prop(channel, expand_prop, text='Base Alpha:', emboss=False)

        # Alpha input value
        alpha_index = channel.io_index + 1
        if alpha_index < len(node.inputs):
            alpha_inp = node.inputs[alpha_index]
            rrow = brow.row(align=True)
            rrow.alignment = 'RIGHT'
            if len(alpha_inp.links) == 0:
                brow.prop(alpha_inp, 'default_value', text='')
            else:
                brow.label(text='', icon='LINKED')
    else:
        icon = 'TRIA_DOWN' if is_expanded else 'TRIA_RIGHT'
        if hasattr(channel, expand_prop):
            rrow.prop(channel, expand_prop, text='', emboss=False, icon=icon)
            rrow.prop(channel, expand_prop, text='Alpha:', emboss=False)
        else:
            rrow.label(text='Alpha:')

        rrow = brow.row(align=True)
        rrow.alignment = 'RIGHT'

    brow.prop(channel, 'enable_alpha', text='')

    # Expanded alpha settings
    if is_expanded and hasattr(channel, expand_prop):
        brow = layout.row(align=True)
        brow.label(text='', icon='BLANK1')
        bbox = brow.box()
        bbcol = bbox.column()
        bbcol.active = channel.enable_alpha

        if channel.enable_alpha:
            # Base Alpha value
            alpha_index = channel.io_index + 1
            if alpha_index < len(node.inputs):
                alpha_inp = node.inputs[alpha_index]
                arow = bbcol.row(align=True)
                arow.label(text='Base Alpha:')
                if len(alpha_inp.links) == 0:
                    arow.prop(alpha_inp, 'default_value', text='')
                else:
                    arow.label(text='', icon='LINKED')

        # Blend mode
        if hasattr(channel, 'alpha_blend_mode'):
            arow = bbcol.row(align=True)
            arow.label(text='Blend Mode:')
            arow.prop(channel, 'alpha_blend_mode', text='')

        # Shadow mode
        if hasattr(channel, 'alpha_shadow_mode'):
            arow = bbcol.row(align=True)
            arow.label(text='Shadow Mode:')
            arow.prop(channel, 'alpha_shadow_mode', text='')

        # Backface mode
        if hasattr(channel, 'backface_mode'):
            arow = bbcol.row(align=True)
            arow.label(text='Backface Mode:')
            arow.prop(channel, 'backface_mode', text='')


def _draw_normal_settings(layout, channel):
    """Draw settings specific to normal channels matching ucupaint style.

    Args:
        layout: UI layout to draw into.
        channel: MPaintChannel to configure.
    """
    # ========== SMOOTH BUMP ==========
    if hasattr(channel, 'enable_smooth_bump'):
        brow = layout.row(align=True)

        expand_prop = 'expand_smooth_bump_settings'
        is_expanded = getattr(channel, expand_prop, False) if hasattr(channel, expand_prop) else False

        rrow = brow.row(align=True)
        if hasattr(channel, expand_prop):
            icon = 'TRIA_DOWN' if is_expanded else 'TRIA_RIGHT'
            rrow.prop(channel, expand_prop, text='', emboss=False, icon=icon)
            rrow.prop(channel, expand_prop, text='Smoother Bump:', emboss=False)
        else:
            rrow.label(text='Smoother Bump:')

        rrow = brow.row(align=True)
        rrow.alignment = 'RIGHT'
        brow.prop(channel, 'enable_smooth_bump', text='')

    # ========== PARALLAX SETTINGS ==========
    if hasattr(channel, 'enable_parallax'):
        brow = layout.row(align=True)

        expand_prop = 'expand_parallax_settings'
        is_expanded = getattr(channel, expand_prop, False) if hasattr(channel, expand_prop) else False

        rrow = brow.row(align=True)
        if hasattr(channel, expand_prop):
            icon = 'TRIA_DOWN' if is_expanded else 'TRIA_RIGHT'
            rrow.prop(channel, expand_prop, text='', emboss=False, icon=icon)
            rrow.prop(channel, expand_prop, text='Parallax:', emboss=False)
        else:
            rrow.label(text='Parallax:')

        rrow = brow.row(align=True)
        rrow.alignment = 'RIGHT'
        brow.prop(channel, 'enable_parallax', text='')

        if is_expanded and hasattr(channel, expand_prop):
            brow = layout.row(align=True)
            brow.label(text='', icon='BLANK1')
            bbox = brow.box()
            bbcol = bbox.column()
            bbcol.active = channel.enable_parallax

            if hasattr(channel, 'parallax_num_of_layers'):
                prow = bbcol.row(align=True)
                prow.label(text='Layers:')
                prow.prop(channel, 'parallax_num_of_layers', text='')

            if hasattr(channel, 'parallax_height_tweak'):
                prow = bbcol.row(align=True)
                prow.label(text='Height Tweak:')
                prow.prop(channel, 'parallax_height_tweak', text='')

    # ========== DISPLACEMENT SETTINGS ==========
    if hasattr(channel, 'enable_subdiv_setup'):
        brow = layout.row(align=True)

        expand_prop = 'expand_subdiv_settings'
        is_expanded = getattr(channel, expand_prop, False) if hasattr(channel, expand_prop) else False

        rrow = brow.row(align=True)
        if hasattr(channel, expand_prop):
            icon = 'TRIA_DOWN' if is_expanded else 'TRIA_RIGHT'
            rrow.prop(channel, expand_prop, text='', emboss=False, icon=icon)
            rrow.prop(channel, expand_prop, text='Displacement:', emboss=False)
        else:
            rrow.label(text='Displacement:')

        rrow = brow.row(align=True)
        rrow.alignment = 'RIGHT'
        brow.prop(channel, 'enable_subdiv_setup', text='')

        if is_expanded and hasattr(channel, expand_prop):
            brow = layout.row(align=True)
            brow.label(text='', icon='BLANK1')
            bbox = brow.box()
            bbcol = bbox.column()
            bbcol.active = channel.enable_subdiv_setup

            if hasattr(channel, 'subdiv_adaptive'):
                drow = bbcol.row(align=True)
                drow.label(text='Adaptive:')
                drow.prop(channel, 'subdiv_adaptive', text='')

            if hasattr(channel, 'subdiv_on_max_polys'):
                drow = bbcol.row(align=True)
                drow.label(text='Max Polys (K):')
                drow.prop(channel, 'subdiv_on_max_polys', text='')

# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Panel definitions for the Texture Sets space.

Single column layout like the Texturing Layers space.
"""

import bpy
from bpy.types import Panel


def _draw_texture_sets_tab(context, layout, obj):
    """Draw the Texture Sets tab content (material slots management).

    Args:
        context: Blender context.
        layout: UI layout to draw into.
        obj: Active object.
    """
    col = layout.column(align=True)

    # Material slots list
    is_sortable = len(obj.material_slots) > 1
    rows = 4 if is_sortable else 2

    row = col.row()
    row.template_list(
        "MATERIAL_UL_matslots", "",
        obj, "material_slots",
        obj, "active_material_index",
        rows=rows
    )

    # Buttons column
    sub = row.column(align=True)
    sub.operator("wm.m_add_material_slot", icon='ADD', text="")
    sub.operator("wm.m_remove_material_slot", icon='REMOVE', text="")
    if is_sortable:
        sub.separator()
        sub.operator("wm.m_move_material_slot", icon='TRIA_UP', text="").direction = 'UP'
        sub.operator("wm.m_move_material_slot", icon='TRIA_DOWN', text="").direction = 'DOWN'

    # Material selector
    col.separator()
    col.template_ID(obj, "active_material", new="material.new")

    # Edit mode buttons
    if obj.mode == 'EDIT':
        col.separator()
        row = col.row(align=True)
        row.operator("object.material_slot_assign", text="Assign")
        row.operator("object.material_slot_select", text="Select")
        row.operator("object.material_slot_deselect", text="Deselect")


def _draw_channel_settings_tab(context, layout):
    """Draw the Channel Settings tab content (channel list and settings directly, no dropdown).

    Args:
        context: Blender context.
        layout: UI layout to draw into.
    """
    from ...paint.core.node.node_utils import get_active_mpaint_node
    from ...paint.core.lib.lib import channel_custom_icon_dict
    from ...paint.core.lib.lib_operations import get_icon

    node = get_active_mpaint_node()
    if not node or not node.node_tree:
        layout.label(text="No Mixar material active", icon='INFO')
        return

    mp = node.node_tree.mp
    wm = context.window_manager
    if not hasattr(wm, 'mpui'):
        layout.label(text="Paint UI not initialized", icon='INFO')
        return
    mpui = wm.mpui

    # ========== CHANNELS BOX ==========
    box = layout.box()
    box.label(text="Channels", icon='NODE_COMPOSITING')

    col = box.column()

    channel_count = len(mp.channels)

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

    # ========== CHANNEL SETTINGS (if channel selected) ==========
    if channel_count > 0 and mp.active_channel_index >= 0 and mp.active_channel_index < len(mp.channels):
        col.separator(factor=0.5)

        channel = mp.channels[mp.active_channel_index]

        # Channel settings box
        settings_box = col.box()

        # Header with channel name and icon
        header_row = settings_box.row(align=True)

        # Channel type icon - try custom icons first
        icon_name = channel_custom_icon_dict.get(channel.type, 'rgb_channel')
        icon_value = get_icon(icon_name)

        if icon_value:
            header_row.label(text=f"{channel.name} Settings", icon_value=icon_value)
        else:
            # Fallback to standard icons
            fallback_icons = {'VALUE': 'SHADING_TEXTURE', 'RGB': 'COLOR', 'NORMAL': 'NORMALS_FACE'}
            type_icon = fallback_icons.get(channel.type, 'DOT')
            header_row.label(text=f"{channel.name} Settings", icon=type_icon)

        # Draw channel settings content
        _draw_channel_settings_content(settings_box, channel, node, mp)


def _draw_channel_settings_content(layout, channel, node, mp):
    """Draw the actual channel settings controls.

    Args:
        layout: UI layout to draw into.
        channel: MPaintChannel to configure.
        node: Active MPaint node.
        mp: MPaint property group.
    """
    col = layout.column()

    # Get the input socket for this channel
    io_index = channel.io_index
    inp = node.inputs[io_index] if 0 <= io_index < len(node.inputs) else None

    # ========== BACKGROUND / BASE VALUE ==========
    if channel.type in {'RGB', 'VALUE'}:
        row = col.row(align=True)
        if channel.type == 'RGB':
            row.label(text='Background:')
        elif channel.type == 'VALUE':
            row.label(text='Base Value:')

        if inp:
            if len(inp.links) == 0:
                row.prop(inp, 'default_value', text='')
            else:
                row.label(text='', icon='LINKED')

    # ========== ALPHA SETTINGS (RGB only) ==========
    if channel.type == 'RGB' and hasattr(channel, 'enable_alpha'):
        row = col.row(align=True)
        row.label(text='Alpha:')
        row.prop(channel, 'enable_alpha', text='')

        if channel.enable_alpha:
            # Base Alpha value
            alpha_index = channel.io_index + 1
            if alpha_index < len(node.inputs):
                alpha_inp = node.inputs[alpha_index]
                arow = col.row(align=True)
                arow.label(text='Base Alpha:')
                if len(alpha_inp.links) == 0:
                    arow.prop(alpha_inp, 'default_value', text='')
                else:
                    arow.label(text='', icon='LINKED')

    # ========== USE CLAMP ==========
    if channel.type in {'RGB', 'VALUE'}:
        row = col.row(align=True)
        row.label(text='Use Clamp:')
        row.prop(channel, 'use_clamp', text='')

    # ========== COLORSPACE ==========
    if channel.type in {'RGB', 'VALUE'} and hasattr(channel, 'colorspace'):
        row = col.row(align=True)
        row.label(text='Colorspace:')
        row.prop(channel, 'colorspace', text='')

    # ========== NORMAL CHANNEL SETTINGS ==========
    if channel.type == 'NORMAL':
        if hasattr(channel, 'enable_smooth_bump'):
            row = col.row(align=True)
            row.label(text='Smoother Bump:')
            row.prop(channel, 'enable_smooth_bump', text='')

        if hasattr(channel, 'enable_parallax'):
            row = col.row(align=True)
            row.label(text='Parallax:')
            row.prop(channel, 'enable_parallax', text='')

        if hasattr(channel, 'enable_subdiv_setup'):
            row = col.row(align=True)
            row.label(text='Displacement:')
            row.prop(channel, 'enable_subdiv_setup', text='')


class TEXTURE_SETS_PT_main(Panel):
    """Main panel for Texture Sets space - single column layout."""
    bl_label = "Texture Sets"
    bl_idname = "TEXTURE_SETS_PT_main"
    bl_space_type = 'TEXTURE_SETS'
    bl_region_type = 'WINDOW'
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        obj = context.object or context.active_object

        # Top padding
        layout.separator()

        # Get mixar_ui for tab state
        wm = context.window_manager
        mixar_ui = wm.mixar_ui if hasattr(wm, 'mixar_ui') else None

        if not mixar_ui:
            layout.label(text="UI state not initialized", icon='ERROR')
            return

        # ========== TAB ROW ==========
        tab_row = layout.row(align=True)
        tab_row.scale_y = 1.5
        tab_row.prop(mixar_ui, "texture_sets_tab", expand=True)

        layout.separator()

        # ========== CONDITIONAL CONTENT BASED ON TAB ==========
        if mixar_ui.texture_sets_tab == 'TEXTURE_SETS':
            # TEXTURE SETS TAB
            if not obj or obj.type not in {'MESH', 'META', 'CURVE', 'CURVES', 'SURFACE', 'FONT'}:
                layout.label(text="Select a mesh object", icon='INFO')
                return

            _draw_texture_sets_tab(context, layout, obj)

        elif mixar_ui.texture_sets_tab == 'CHANNEL_SETTINGS':
            # CHANNEL SETTINGS TAB
            _draw_channel_settings_tab(context, layout)


classes = (
    TEXTURE_SETS_PT_main,
)

# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drawing functions for the Asset Export tab of the baking panel.

Per-format settings are drawn using the native Blender export panel
functions (glTF, FBX) or a manual recreation (OBJ, whose draw lives
in C++).  All property data lives on WindowManager PropertyGroups.
"""

import bpy


def draw_asset_export_section(layout, mp, node, context):
    """Draw the full Asset Export tab content."""
    wm = context.window_manager
    s = getattr(wm, 'mixar_asset_export', None)
    if not s:
        layout.label(text="Export settings unavailable", icon='ERROR')
        return

    _draw_format_section(layout, wm, s)

    layout.separator()

    _draw_action_buttons(layout, mp)


def _draw_format_section(layout, wm, s):
    """Draw format tab selector and the matching native export panels."""
    box = layout.box()
    box.label(text="Export Format", icon='FILE_3D')

    row = box.row(align=True)
    row.scale_y = 1.3
    row.prop(s, "tab", expand=True)

    # Preset selector row
    tab = s.tab
    preset_row = box.row(align=True)
    if tab == 'GLTF':
        preset_row.menu("MIXAR_MT_gltf_export_presets",
                        text=bpy.types.MIXAR_MT_gltf_export_presets.bl_label)
        preset_row.operator("mixar.gltf_export_preset_add",
                            text="", icon='ADD')
        op = preset_row.operator("mixar.gltf_export_preset_add",
                                 text="", icon='REMOVE')
        op.remove_active = True
    elif tab == 'OBJ':
        preset_row.menu("MIXAR_MT_obj_export_presets",
                        text=bpy.types.MIXAR_MT_obj_export_presets.bl_label)
        preset_row.operator("mixar.obj_export_preset_add",
                            text="", icon='ADD')
        op = preset_row.operator("mixar.obj_export_preset_add",
                                 text="", icon='REMOVE')
        op.remove_active = True
    elif tab == 'FBX':
        preset_row.menu("MIXAR_MT_fbx_export_presets",
                        text=bpy.types.MIXAR_MT_fbx_export_presets.bl_label)
        preset_row.operator("mixar.fbx_export_preset_add",
                            text="", icon='ADD')
        op = preset_row.operator("mixar.fbx_export_preset_add",
                                 text="", icon='REMOVE')
        op.remove_active = True

    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = False

    if tab == 'GLTF':
        _draw_gltf_panels(col, wm)
    elif tab == 'OBJ':
        _draw_obj_panels(col, wm)
    elif tab == 'FBX':
        _draw_fbx_panels(col, wm)


def _draw_gltf_panels(col, wm):
    """Draw glTF export panels using the native add-on draw functions."""
    gs = getattr(wm, 'mixar_export_gltf', None)
    if not gs:
        col.label(text="glTF settings unavailable", icon='ERROR')
        return
    try:
        from io_scene_gltf2 import (
            export_main,
            export_panel_include,
            export_panel_transform,
            export_panel_data,
            export_panel_animation,
        )
        export_main(col, gs, True)
        export_panel_include(col, gs, True)
        export_panel_transform(col, gs)
        export_panel_data(col, gs)
        export_panel_animation(col, gs)
    except ImportError:
        col.label(text="glTF add-on not available", icon='ERROR')


def _draw_obj_panels(col, wm):
    """Draw OBJ export panels (manually recreated from C++ draw)."""
    os = getattr(wm, 'mixar_export_obj', None)
    if not os:
        col.label(text="OBJ settings unavailable", icon='ERROR')
        return
    from ..asset_export.obj_export_operator import draw_obj_export_panels
    draw_obj_export_panels(col, os, is_file_browser=True)


def _draw_fbx_panels(col, wm):
    """Draw FBX export panels using the native add-on draw functions."""
    fs = getattr(wm, 'mixar_export_fbx', None)
    if not fs:
        col.label(text="FBX settings unavailable", icon='ERROR')
        return
    try:
        from io_scene_fbx import (
            export_main,
            export_panel_include,
            export_panel_transform,
            export_panel_geometry,
            export_panel_armature,
            export_panel_animation,
        )
        export_main(col, fs, True)
        export_panel_include(col, fs, True)
        export_panel_transform(col, fs)
        export_panel_geometry(col, fs)
        export_panel_armature(col, fs)
        export_panel_animation(col, fs)
    except ImportError:
        col.label(text="FBX add-on not available", icon='ERROR')


def _draw_action_buttons(layout, mp):
    """Draw separate Bake/Rebake and Export buttons.

    Bake is always available; after baking it reads "Rebake".
    Export is disabled until channels are baked.
    """
    col = layout.column(align=True)

    # Bake / Rebake
    bake_row = col.row(align=True)
    bake_row.scale_y = 1.5
    bake_text = "Rebake Channels" if mp.use_baked else "Bake Channels"
    bake_icon = 'FILE_REFRESH' if mp.use_baked else 'RENDER_STILL'
    bake_op = bake_row.operator(
        "wm.m_bake_channels",
        text=bake_text,
        icon=bake_icon,
    )
    bake_op.only_active_channel = False

    col.separator(factor=0.5)

    # Export (enabled only after bake)
    export_row = col.row(align=True)
    export_row.scale_y = 1.5
    export_row.enabled = mp.use_baked
    export_row.operator(
        "wm.m_export_asset",
        text="Export",
        icon='EXPORT',
    )

    if not mp.use_baked:
        col.separator(factor=0.3)
        col.label(text="Bake channels first to enable export", icon='INFO')

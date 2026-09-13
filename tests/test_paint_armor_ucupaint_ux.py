# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""ArmorPaint / Ucupaint UX that Mixar can host without the Iron engine.

DeepWiki on armory3d/armorpaint and ucupumar/ucupaint maps these to Mixar's
existing layer stack: lazy-mouse stroke, surface rejection, stencil/clone,
layer isolate, channel isolate, merge/invert, and backface-always-up.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAINT = ROOT / "src/scripts/mixar/modules/paint"


def _read(rel: str) -> str:
    return (PAINT / rel).read_text(encoding="utf-8")


def test_brush_tool_tab_exposes_armorpaint_surface_and_lazy_mouse():
    brush = _read("ui/utils/ui_brush_panels.py")
    inline = _read("ui/utils/ui_helpers_brush.py")
    assert "use_smooth_stroke" in brush
    assert "_draw_surface_projection_section" in brush
    assert "_draw_stencil_section" in brush
    assert "_draw_clone_section" in brush
    assert "use_normal_falloff" in brush
    assert "use_smooth_stroke" in inline
    assert "use_stencil_layer" in inline
    assert "use_clone_layer" in inline


def test_layer_ops_expose_isolate_merge_and_invert():
    ops = _read("ui/operators/layer_selection_ops.py")
    toolbar = _read("ui/utils/ui_helpers_toolbar.py")
    menu = _read("ui/operators/layer_menu_ops.py")
    assert 'bl_idname = "layers.toggle_layer_preview"' in ops
    assert 'bl_idname = "layers.isolate_channel"' in ops
    assert 'bl_idname = "layers.invert_active_layer_image"' in ops
    assert 'bl_idname = "layers.color_id_to_mask"' in ops
    assert "layers.toggle_layer_preview" in toolbar
    assert "wm.m_merge_layer" in toolbar
    assert "layers.invert_active_layer_image" in toolbar
    assert "layers.toggle_layer_preview" in menu
    assert "wm.m_merge_layer" in menu


def test_channel_isolate_buttons_and_backface_always_up_are_drawn():
    channels = _read("ui/utils/ui_channel_panels.py")
    texture_sets = _read("ui/utils/ui_helpers_texture_sets_channels.py")
    props = _read("ui/properties/main_paint_properties.py")
    assert "_draw_channel_isolate_row" in channels
    assert "layers.isolate_channel" in channels
    assert "enable_backface_always_up" in channels
    assert "layers.isolate_channel" in texture_sets
    assert "enable_backface_always_up" in texture_sets
    assert "enable_backface_always_up" in props
    assert "layer_preview_mode" in props
    assert "preview_mode" in props


def test_toolbar_and_new_layer_menu_expose_group_and_patterns():
    toolbar = _read("ui/utils/ui_helpers_toolbar.py")
    new_menu = _read("ui/menus/layer_menus.py")
    assert 'LAYERS_MT_procedural_layer_menu' in toolbar
    assert "layers.add_layer_group" in toolbar
    assert "layers.add_advanced_layer" in new_menu
    assert "layers.add_layer_group" in new_menu
    assert "LAYERS_MT_procedural_layer_menu" in new_menu


def test_layer_list_and_panel_expose_solo_and_preview_type():
    uilist = _read("ui/lists/layer_uilist.py")
    panel = _read("ui/panels/layers_panel.py")
    masks = _read("ui/operators/mask_operators.py")
    assert "layers.toggle_layer_preview" in uilist
    assert "layer_preview_mode_type" in panel
    assert "layers.color_id_to_mask" in masks

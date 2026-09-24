# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Drawer resize and graph dispatch regressions; real gestures live in QA."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
EDITOR = ROOT / 'src/source/blender/editors'
MODULE = ROOT / 'src/scripts/mixar/modules/moodboard'


@pytest.mark.parametrize('modifier', [{'ctrl': True}, {'oskey': True}])
def test_active_pointer_map_hits_graph_before_media_fallback(modifier):
    source = ast.parse((MODULE / 'ui/keymap.py').read_text())
    bind = next(node for node in source.body
                if isinstance(node, ast.FunctionDef) and node.name == '_bind_moodboard_pointer')
    items = []

    def new(idname, event, value, **modifiers):
        item = SimpleNamespace(idname=idname, event=event, value=value,
                               modifiers=modifiers, properties=SimpleNamespace())
        items.append(item)
        return item

    namespace = {'addon_keymaps': [], 'get_keymap_modifier': lambda: modifier}
    exec(compile(ast.Module(body=[bind], type_ignores=[]), '<keymap>', 'exec'), namespace)
    namespace['_bind_moodboard_pointer'](SimpleNamespace(keymap_items=SimpleNamespace(new=new)))
    # wm_keymap_addon_add uses BLI_addhead on every addon item. Exercise the
    # resulting dispatch order, since inspecting registration order hid this.
    active = list(reversed(items))
    for extras in ({}, {'shift': True}, modifier):
        press = [item for item in active if item.event == 'LEFTMOUSE'
                 and item.value == 'PRESS' and item.modifiers == extras]
        # Same order space_mixie.cc registers: frames claim their own chrome
        # first and pass through on their interior, then cards, then media.
        # Without the frame item in the ADDON map a keyconfig preset reload
        # left frames unselectable.
        expected = ['mixie.moodboard_frame_select',
                    'mixie.moodboard_graph_select',
                    'mixie.moodboard_select_image']
        if not extras:
            expected.insert(0, 'mixie.moodboard_annotation_stroke')
            expected.insert(0, 'mixie.moodboard_annotation_erase')
        assert [item.idname for item in press] == expected
        if extras:
            assert all(item.properties.extend for item in press)


def test_socket_menus_keep_the_originating_canvas_region():
    # The right-click resolver lives in its own unit (500-line rule); every
    # graph file that opens a menu still has to keep the drawer region.
    openers = ('mixie_moodboard_ops_graph_context.cc',
               'mixie_moodboard_ops_graph_link.cc')
    for name in ('mixie_moodboard_ops_graph.cc',) + openers:
        source = (EDITOR / 'space_mixie' / name).read_text()
        assert 'OpCallContext::InvokeRegionWin' not in source
    for name in openers:
        source = (EDITOR / 'space_mixie' / name).read_text()
        assert 'WM_operator_name_call_ptr(' in source
        assert 'OpCallContext::InvokeDefault' in source
    output_menu = (MODULE / 'ui/moodboard_output_menu.py').read_text()
    assert "layout.operator_context = 'INVOKE_DEFAULT'" in output_menu


def test_grip_geometry_reads_the_resized_region():
    geometry = (EDITOR / 'include/ED_moodboard_drawer.hh').read_text()
    grip = geometry.split('inline bool view3d_moodboard_drawer_grip_rect_for')[1]
    assert 'VIEW3D_MOODBOARD_DRAWER_WIDTH' not in grip
    assert 'region->winrct.xmin' in grip and 'region->winrct.xmax' in grip
    draw = (EDITOR / 'space_view3d/view3d_moodboard_drawer_draw.cc').read_text()
    assert 'ED_area_tag_region_size_update' not in draw


def test_resize_preserves_right_edge_and_pixel_zoom():
    source = (EDITOR / 'space_view3d/view3d_moodboard_drawer.cc').read_text()
    assert 'const int previous_width = region->v2d.winx;' in source
    assert 'const int previous_width = BLI_rcti_size_x(&region->v2d.mask)' not in source
    assert 'saved_cur.xmin = saved_cur.xmax -' in source
    assert 'float(region->winx) / float(previous_width)' in source
    assert 'drawer_region_size_pin' not in source

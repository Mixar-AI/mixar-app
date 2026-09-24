# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The retired right sidebar must stay empty across catalog refreshes."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / 'src/scripts/mixar/modules'


def test_sidebar_has_no_panel_definitions_or_registration():
    source = (MODULES / 'moodboard/ui/moodboard_sidebar_panels.py').read_text()
    tree = ast.parse(source)
    assert not any(isinstance(node, ast.ClassDef) for node in tree.body)
    classes = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'classes'
                           for t in node.targets))
    assert ast.literal_eval(classes) == ()
    mapping = next(node.value for node in tree.body if isinstance(node, ast.Expr)
                   and isinstance(node.value, ast.Call)
                   and isinstance(node.value.func, ast.Name)
                   and node.value.func.id == '_init_capability_tabs')
    assert ast.literal_eval(mapping.args[0]) == {}


def test_common_mode_selector_cannot_repopulate_the_sidebar():
    tree = ast.parse((MODULES / 'common/__init__.py').read_text())
    assert not any(isinstance(node, ast.ClassDef)
                   and node.name == 'MIXIE_PT_mode_selector' for node in tree.body)
    operators = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert {'MIXIE_OT_set_mode', 'MIXIE_OT_placeholder'} <= operators


def _function(path, name):
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


def test_director_opens_video_after_island_restore(monkeypatch):
    import sys
    from types import SimpleNamespace

    focus = _function(MODULES / 'director/core/handoff.py', 'focus_video_generation')
    wm = SimpleNamespace(mixar_bubble_tab='IMAGE')
    region = SimpleNamespace(active_panel_category='')
    context = SimpleNamespace(window_manager=wm, region=region)

    def open_window():
        wm.mixar_bubble_tab = 'AGENT'
        return {'FINISHED'}

    monkeypatch.setitem(sys.modules, 'bpy', SimpleNamespace(
        ops=SimpleNamespace(mixar=SimpleNamespace(agent_bubble_open_window=open_window))))
    assert focus(context)
    assert wm.mixar_bubble_tab == 'VIDEO'
    assert region.active_panel_category == ''


def test_director_does_not_claim_unavailable_video_form_was_opened(monkeypatch):
    import sys
    from types import SimpleNamespace

    focus = _function(MODULES / 'director/core/handoff.py', 'focus_video_generation')
    wm = SimpleNamespace(mixar_bubble_tab='IMAGE')
    monkeypatch.setitem(sys.modules, 'bpy', SimpleNamespace(ops=SimpleNamespace(
        mixar=SimpleNamespace(agent_bubble_open_window=lambda: {'CANCELLED'}))))
    assert not focus(SimpleNamespace(window_manager=wm))
    assert wm.mixar_bubble_tab == 'IMAGE'


def test_retired_native_sidebar_cannot_reserve_space_or_reopen():
    source = (ROOT / 'src/source/blender/editors/space_mixie/space_mixie.cc').read_text()
    registration = source.split('/* Retain the type for old files,')[1].split('BLI_addhead')[0]
    assert 'art->regionid = RGN_TYPE_UI;' in registration
    assert 'art->poll = [](const RegionPollParams *) { return false; };' in registration
    assert 'EVT_NKEY' not in source
    addon = (MODULES / 'moodboard/ui/keymap.py').read_text()
    assert 'screen.region_toggle' not in addon


def test_retired_native_sidebar_has_no_persisted_scrollbar_or_resize_azones():
    source = (ROOT / 'src/source/blender/editors/screen/area.cc').read_text()
    function = source.split('static void region_azones_add(')[1].split('/* Quad View')[0]
    assert 'area->spacetype == SPACE_MIXIE && region->regiontype == RGN_TYPE_UI' in function
    guard = function.split('area->spacetype == SPACE_MIXIE')[1].split('}')[0]
    assert 'return;' in guard
    # The retirement belongs to this editor, never the View3D N-panel.
    assert 'SPACE_VIEW3D' not in function

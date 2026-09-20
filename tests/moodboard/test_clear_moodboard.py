# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Whole-board clear regression; real undo and both canvas hosts use GUI QA."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


COLLECTIONS = ('images', 'textboxes', 'groups', 'action_nodes', 'asset_nodes',
               'links', 'annotations')


@pytest.fixture
def clear_board():
    source = Path(__file__).resolve().parents[2] / (
        'src/scripts/mixar/modules/moodboard/ui/operators/transform_ops.py')
    tree = ast.parse(source.read_text())
    tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == 'MIXIE_OT_clear_moodboard']
    release = Mock()
    redraw = Mock()
    scope = {'Operator': object, 'release_all_moodboard_images': release,
             'redraw_moodboard_canvases': redraw}
    exec(compile(tree, str(source), 'exec'), scope)
    op = scope['MIXIE_OT_clear_moodboard']()
    op.report = Mock()
    scene = SimpleNamespace(**{f'mixie_moodboard_{name}': [] for name in COLLECTIONS},
                            mixie_moodboard_active_node_id='')
    return op, SimpleNamespace(scene=scene), release, redraw


def test_annotation_only_board_can_be_cleared(clear_board):
    op, context, release, redraw = clear_board
    context.scene.mixie_moodboard_annotations.extend([object(), object()])

    assert op.execute(context) == {'FINISHED'}
    assert not context.scene.mixie_moodboard_annotations
    op.report.assert_called_once_with({'INFO'}, 'Cleared 2 annotation stroke(s)')
    redraw.assert_called_once_with()


def test_mixed_board_clears_every_content_type_and_releases_images(clear_board):
    op, context, release, redraw = clear_board
    scene = context.scene
    for name in COLLECTIONS:
        getattr(scene, f'mixie_moodboard_{name}').append(object())
    scene.mixie_moodboard_active_node_id = 'active-node'

    # Image ownership must be released before the owning entries disappear.
    release.side_effect = lambda s: bool(s.mixie_moodboard_images) or pytest.fail(
        'Image entries were removed before image lifecycle cleanup')
    assert op.execute(context) == {'FINISHED'}
    assert all(not getattr(scene, f'mixie_moodboard_{name}') for name in COLLECTIONS)
    assert scene.mixie_moodboard_active_node_id == ''
    release.assert_called_once_with(scene)
    redraw.assert_called_once_with()
    assert '1 annotation stroke(s)' in op.report.call_args.args[1]


def test_empty_board_does_not_add_an_undo_step(clear_board):
    op, context, release, redraw = clear_board

    assert op.execute(context) == {'CANCELLED'}
    op.report.assert_called_once_with({'INFO'}, 'Moodboard is already empty')
    release.assert_not_called()
    redraw.assert_not_called()


@pytest.fixture
def has_content():
    source = Path(__file__).resolve().parents[2] / (
        'src/scripts/mixar/modules/moodboard/core/canvas_context.py')
    tree = ast.parse(source.read_text())
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if 'MOODBOARD_CONTENT_COLLECTIONS' in names:
                keep.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == 'has_moodboard_content':
            keep.append(node)
    tree.body = keep
    scope = {}
    exec(compile(tree, str(source), 'exec'), scope)
    return scope['has_moodboard_content']


@pytest.mark.parametrize('name', COLLECTIONS)
def test_clear_button_is_available_for_each_content_type(clear_board, has_content, name):
    _, context, _, _ = clear_board
    assert not has_content(context)
    getattr(context.scene, f'mixie_moodboard_{name}').append(object())
    assert has_content(context)


def test_header_can_draw_before_moodboard_properties_are_registered(has_content):
    assert not has_content(SimpleNamespace(scene=SimpleNamespace()))


def test_zen_drawer_hosts_a_corner_clear_action():
    root = Path(__file__).resolve().parents[2]
    draw = (root / "src/source/blender/editors/space_view3d/view3d_moodboard_drawer_draw.cc").read_text()
    header = (root / "src/scripts/mixar/modules/space_mixie/ui/header.py").read_text()

    assert '"moodboard_drawer_clear"' in draw
    assert "draw_clear_tool(C, region, panel_xmin)" in draw
    assert 'uiDefIconTextButO' in draw
    assert "ICON_X" in draw
    assert '"Clear"' in draw
    assert "mixie.clear_moodboard" in draw
    assert "MixarComponent::Action" in draw
    assert "compact_density.control_height" in draw
    assert "MixarTextRole::Body" in draw
    assert "0.75f * scale" in draw
    assert "mixie.clear_moodboard" in header

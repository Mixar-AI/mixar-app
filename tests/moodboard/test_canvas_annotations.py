# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Execute stroke logic outside bpy; native persistence/input are covered by GUI QA."""

import ast
import math
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest


class Collection(list):
    def __init__(self, factory):
        super().__init__()
        self.factory = factory

    def add(self):
        item = self.factory()
        self.append(item)
        return item

    def remove(self, index):
        self.pop(index)


@pytest.fixture
def drawing():
    source = Path(__file__).resolve().parents[2] / (
        'src/scripts/mixar/modules/moodboard/ui/operators/canvas_annotation_ops.py')
    tree = ast.parse(source.read_text())
    tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    scope = {'Operator': object, 'math': math, 'ANNOTATION_MAX_POINTS_PER_STROKE': 4,
             'CANVAS_ANNOTATION_SAMPLE_PX': 2.0, 'is_moodboard_context': lambda c: True,
             'redraw_moodboard_canvases': Mock()}
    exec(compile(tree, str(source), 'exec'), scope)
    strokes = Collection(lambda: NS(points=Collection(lambda: NS(x=0, y=0))))
    context = NS(
        scene=NS(mixie_moodboard_annotations=strokes, mixie_moodboard_show_annotations=False,
                 mixie_edit_tool_state=NS(annotation_width=4, annotation_color=(1, .1, 0, 1))),
        window_manager=NS(mixie_moodboard_annotating=True, mixie_moodboard_erasing=False,
                          modal_handler_add=Mock()),
        region=NS(type='TOOL_PROPS', x=100, y=80,
                  view2d=NS(region_to_view=lambda x, y: (x * 2 - 500, y * 2 + 300))),
        window=NS(cursor_modal_set=Mock(), cursor_modal_restore=Mock()),
        preferences=NS(system=NS(ui_scale=2)),
    )
    return scope['MIXIE_OT_moodboard_annotation_stroke'](), context


def event(x=150, y=120, type='LEFTMOUSE', value='PRESS'):
    return NS(mouse_x=x, mouse_y=y, type=type, value=value)


def test_points_use_unbounded_canvas_coordinates_and_scaled_brush_width(drawing):
    op, context = drawing
    assert op.invoke(context, event()) == {'RUNNING_MODAL'}
    stroke = context.scene.mixie_moodboard_annotations[0]
    assert (stroke.points[0].x, stroke.points[0].y) == (-400, 380)
    assert stroke.width == 16
    assert stroke.color == (1, .1, 0, 1)
    assert context.scene.mixie_moodboard_show_annotations


def test_release_includes_short_endpoint_and_leaves_tool_ready_for_another_stroke(drawing):
    op, context = drawing
    op.invoke(context, event())
    op.modal(context, event(x=151, type='MOUSEMOVE', value='NOTHING'))
    assert len(op._stroke.points) == 1  # Under two screen pixels.
    assert op.modal(context, event(x=151, value='RELEASE')) == {'FINISHED'}
    assert len(op._stroke.points) == 2
    assert context.window_manager.mixie_moodboard_annotating
    context.window.cursor_modal_restore.assert_called_once()


@pytest.mark.parametrize('type', ['ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'])
def test_cancel_removes_only_the_inflight_stroke(drawing, type):
    op, context = drawing
    earlier = context.scene.mixie_moodboard_annotations.add()
    op.invoke(context, event())
    assert op.modal(context, event(type=type)) == {'CANCELLED'}
    assert context.scene.mixie_moodboard_annotations == [earlier]
    context.window.cursor_modal_restore.assert_called_once()


def test_sampling_is_bounded_and_navigation_cannot_move_canvas_mid_stroke(drawing):
    op, context = drawing
    op.invoke(context, event())
    for x in range(160, 300, 10):
        op.modal(context, event(x=x, type='MOUSEMOVE', value='NOTHING'))
    assert len(op._stroke.points) == 4
    assert op.modal(context, event(type='WHEELUPMOUSE')) == {'RUNNING_MODAL'}
    assert op.modal(context, event(type='Z')) == {'RUNNING_MODAL'}


def test_stroke_poll_releases_normal_selection_when_mode_is_off(drawing):
    op, context = drawing
    assert op.poll(context)
    context.window_manager.mixie_moodboard_annotating = False
    assert not op.poll(context)

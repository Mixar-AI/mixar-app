# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Canvas annotation erase: hit-test is bpy-free; gestures exec outside bpy."""

import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from mixar.modules.moodboard.core.annotation_erase import (
    erase_hits,
    point_segment_distance,
    restore_strokes,
    snapshot_strokes,
    stroke_hits,
)
from mixar.modules.moodboard.core.canvas_mark_mode import set_canvas_mark_mode

ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
OPS = MOODBOARD / "ui/operators/canvas_annotation_ops.py"


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

    def clear(self):
        del self[:]


def _stroke(points, width=4.0, color=(1, 0, 0, 1)):
    stroke = NS(points=Collection(lambda: NS(x=0, y=0)), width=width, color=color)
    for x, y in points:
        point = stroke.points.add()
        point.x, point.y = x, y
    return stroke


def test_point_to_segment_distance_is_shortest_closed_segment():
    assert point_segment_distance(0, 1, 0, 0, 2, 0) == pytest.approx(1.0)
    assert point_segment_distance(-1, 0, 0, 0, 2, 0) == pytest.approx(1.0)
    assert point_segment_distance(3, 0, 0, 0, 2, 0) == pytest.approx(1.0)
    assert point_segment_distance(1, 0, 0, 0, 2, 0) == pytest.approx(0.0)


def test_stroke_hits_dots_and_ribbons():
    assert stroke_hits([(0.0, 0.0)], 2.0, 0.4, 0.0)
    assert not stroke_hits([(0.0, 0.0)], 2.0, 2.0, 0.0)
    assert stroke_hits([(0.0, 0.0), (10.0, 0.0)], 2.0, 5.0, 0.4)
    assert not stroke_hits([(0.0, 0.0), (10.0, 0.0)], 2.0, 5.0, 2.0)
    assert stroke_hits([(0.0, 0.0), (10.0, 0.0)], 2.0, 5.0, 1.6, extra_radius=1.0)


def test_erase_hits_removes_newest_matching_strokes_only():
    strokes = Collection(lambda: _stroke([]))
    keep = _stroke([(0.0, 10.0)], width=1.0)
    hit = _stroke([(0.0, 0.0), (4.0, 0.0)], width=2.0)
    strokes.append(keep)
    strokes.append(hit)
    assert erase_hits(strokes, 2.0, 0.0) == 1
    assert strokes == [keep]


def test_snapshot_restore_round_trips_points_color_and_width():
    strokes = Collection(lambda: _stroke([]))
    original = _stroke([(1.0, 2.0), (3.0, 4.0)], width=8.0, color=(0, 1, 0, 1))
    strokes.append(original)
    snap = snapshot_strokes(strokes)
    strokes.clear()
    restore_strokes(strokes, snap)
    assert len(strokes) == 1
    restored = strokes[0]
    assert [(p.x, p.y) for p in restored.points] == [(1.0, 2.0), (3.0, 4.0)]
    assert restored.width == 8.0
    assert restored.color == (0, 1, 0, 1)


@pytest.fixture
def erasing():
    source = ast.parse(OPS.read_text())
    source.body = [
        node for node in source.body if not isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    scope = {
        "Operator": object,
        "math": __import__("math"),
        "ANNOTATION_MAX_POINTS_PER_STROKE": 4,
        "CANVAS_ANNOTATION_SAMPLE_PX": 2.0,
        "is_moodboard_context": lambda c: True,
        "redraw_moodboard_canvases": Mock(),
        "erase_hits": erase_hits,
        "restore_strokes": restore_strokes,
        "snapshot_strokes": snapshot_strokes,
        "set_canvas_mark_mode": set_canvas_mark_mode,
    }
    exec(compile(source, str(OPS), "exec"), scope)
    strokes = Collection(lambda: _stroke([]))
    context = NS(
        scene=NS(
            mixie_moodboard_annotations=strokes,
            mixie_moodboard_show_annotations=False,
            mixie_edit_tool_state=NS(annotation_width=4, annotation_color=(1, 0.1, 0, 1)),
        ),
        window_manager=NS(
            mixie_moodboard_annotating=False,
            mixie_moodboard_erasing=True,
            modal_handler_add=Mock(),
        ),
        region=NS(
            type="TOOL_PROPS",
            x=100,
            y=80,
            view2d=NS(region_to_view=lambda x, y: (x * 2 - 500, y * 2 + 300)),
        ),
        window=NS(cursor_modal_set=Mock(), cursor_modal_restore=Mock()),
        preferences=NS(system=NS(ui_scale=2)),
    )
    return scope, context


def event(x=150, y=120, type="LEFTMOUSE", value="PRESS"):
    return NS(mouse_x=x, mouse_y=y, type=type, value=value)


def test_erase_removes_the_stroke_under_the_pointer(erasing):
    scope, context = erasing
    strokes = context.scene.mixie_moodboard_annotations
    strokes.append(_stroke([(-400, 380), (-300, 380)], width=20))
    keep = _stroke([(0.0, 0.0)], width=1)
    strokes.append(keep)
    op = scope["MIXIE_OT_moodboard_annotation_erase"]()
    assert op.invoke(context, event()) == {"RUNNING_MODAL"}
    assert op.modal(context, event(value="RELEASE")) == {"FINISHED"}
    assert [(p.x, p.y) for p in strokes[0].points] == [(0.0, 0.0)]
    context.window.cursor_modal_set.assert_called_with("ERASER")
    context.window.cursor_modal_restore.assert_called_once()


def test_erase_miss_and_cancel_do_not_keep_a_removal(erasing):
    scope, context = erasing
    strokes = context.scene.mixie_moodboard_annotations
    strokes.append(_stroke([(1000.0, 1000.0)], width=1))
    op = scope["MIXIE_OT_moodboard_annotation_erase"]()
    assert op.invoke(context, event()) == {"RUNNING_MODAL"}
    assert op.modal(context, event(value="RELEASE")) == {"CANCELLED"}
    assert len(strokes) == 1

    strokes.append(_stroke([(-400, 380)], width=20))
    op = scope["MIXIE_OT_moodboard_annotation_erase"]()
    assert op.invoke(context, event()) == {"RUNNING_MODAL"}
    assert op.modal(context, event(type="ESC")) == {"CANCELLED"}
    assert len(strokes) == 2
    context.window.cursor_modal_restore.assert_called()


def test_mark_modes_are_mutually_exclusive(erasing):
    scope, context = erasing
    annotate = scope["MIXIE_OT_moodboard_annotate_canvas"]()
    erase = scope["MIXIE_OT_moodboard_erase_canvas"]()
    exit_op = scope["MIXIE_OT_moodboard_annotation_exit"]()
    context.window_manager.mixie_moodboard_erasing = False
    assert annotate.execute(context) == {"FINISHED"}
    assert context.window_manager.mixie_moodboard_annotating
    assert not context.window_manager.mixie_moodboard_erasing
    assert erase.execute(context) == {"FINISHED"}
    assert context.window_manager.mixie_moodboard_erasing
    assert not context.window_manager.mixie_moodboard_annotating
    assert exit_op.execute(context) == {"FINISHED"}
    assert not context.window_manager.mixie_moodboard_annotating
    assert not context.window_manager.mixie_moodboard_erasing


def test_erase_poll_releases_when_mode_is_off_or_empty(erasing):
    scope, context = erasing
    op = scope["MIXIE_OT_moodboard_annotation_erase"]()
    assert not op.poll(context)
    context.scene.mixie_moodboard_annotations.append(_stroke([(0.0, 0.0)]))
    assert op.poll(context)
    context.window_manager.mixie_moodboard_erasing = False
    assert not op.poll(context)


def test_drawer_erase_is_wired_through_toolbar_menu_and_keymap():
    toolbar = (MOODBOARD / "ui/moodboard_toolbar.py").read_text(encoding="utf-8")
    menu = (MOODBOARD / "ui/menus/canvas_annotation_menu.py").read_text(encoding="utf-8")
    keymap = (MOODBOARD / "ui/keymap.py").read_text(encoding="utf-8")
    props = (MOODBOARD / "ui/properties/canvas_annotation_props.py").read_text(encoding="utf-8")
    ops = OPS.read_text(encoding="utf-8")
    assert 'bl_idname = "mixie.moodboard_erase_canvas"' in ops
    assert 'bl_idname = "mixie.moodboard_annotation_erase"' in ops
    assert "mixie.moodboard_erase_canvas" in toolbar
    assert "mixie_moodboard_erasing" in toolbar
    assert "mixie.moodboard_erase_canvas" in menu
    assert "mixie.moodboard_annotation_erase" in keymap
    assert 'name="Erase"' in props
    assert '"SKIP_SAVE"' in props

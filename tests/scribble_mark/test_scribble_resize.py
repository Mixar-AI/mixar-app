# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Resizing the app window while Sketch is frozen must not re-render inside
the resize.

macOS and Windows never return to the main loop while a window edge is being
dragged. ``wm_window.cc`` runs timers, handlers, notifiers and drawing from
inside the OS resize callback instead. On macOS that callback runs within
``-[NSWindow _resizeWithEvent:]``, whose autorelease pool sits above the Metal
render boundary opened by ``wm_window_events_process``. The mark modal's
re-freeze calls ``render.opengl``, which ends with ``GPU_render_step(true)``.
That drains the boundary's pool, popping AppKit's pool with it, and AppKit
aborts: "Invalid or prematurely-freed autorelease pool" and SIGKILL.
"""

import ast
import pathlib
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
MODAL = REPO / "src/scripts/mixar/modules/scribble_mark/ui/operators/mark_draw_ops.py"
WM_WINDOW = REPO / "src/source/blender/windowmanager/intern/wm_window.cc"
RNA_WM_MIXAR = REPO / "src/source/blender/makesrna/intern/rna_wm_mixar.cc"


# =============================================================================
# The flag Python reads
# =============================================================================

class TestWindowResizing:
    def test_only_a_real_true_counts(self):
        """A MagicMock window manager (tests, or a build without the RNA
        property) must not read as resizing, or Sketch would never
        re-freeze."""
        from mixar.modules.scribble_mark.core.freeze import window_resizing
        assert window_resizing(NS(window_manager=NS(mixar_window_resizing=True)))
        assert not window_resizing(NS(window_manager=NS(mixar_window_resizing=False)))
        assert not window_resizing(NS(window_manager=NS()))
        assert not window_resizing(NS())
        assert not window_resizing(NS(window_manager=MagicMock()))

    def test_capture_refuses_to_render_during_a_resize(self, monkeypatch):
        """Last line of defence for any caller: no ``render.opengl`` from
        inside the resize callback. ``context`` has no scene, so reaching the
        render settings would raise instead of returning None."""
        from mixar.modules.scribble_mark.core import freeze
        opengl = Mock()
        monkeypatch.setattr(freeze.bpy.ops, "render", NS(opengl=opengl))
        context = NS(window_manager=NS(mixar_window_resizing=True))

        assert freeze.capture_region_still(context, None, None, None, "frame") is None
        opengl.assert_not_called()


# =============================================================================
# The modal defers the re-freeze to the main loop
# =============================================================================

@pytest.fixture
def modal_operator():
    """The real operator class, with ``bpy.types.Operator`` as ``object``.

    ``bpy`` is a MagicMock here, so subclassing its ``Operator`` yields a
    mock with no methods. Executing the module with a plain base keeps
    ``modal`` exactly as written.
    """
    tree = ast.parse(MODAL.read_text())
    tree.body = [
        node for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and node.module == "bpy.types")
    ]
    scope = {"__name__": "mark_draw_ops_under_test", "Operator": object}
    exec(compile(tree, str(MODAL), "exec"), scope)

    op = scope["MIXAR_OT_scribble_mark_draw"]()
    region = NS(x=0, y=0, width=800, height=600)
    op._region = lambda _context: region
    op._talk = None
    op._refreeze_if_resized = Mock(return_value=True)
    op._maybe_commit = Mock()
    op._disarm = Mock()
    op._finish = Mock()
    return op


def _timer_tick(op, resizing):
    context = NS(window_manager=NS(mixar_mark_armed=True, mixar_window_resizing=resizing))
    event = NS(type="TIMER", value="NOTHING", mouse_x=0, mouse_y=0)
    return op.modal(context, event)


def test_a_tick_inside_the_resize_neither_refreezes_nor_commits(modal_operator):
    """Re-freezing renders, and rendering here kills the app. Committing
    waits too: it would measure a mark against a region the still no longer
    matches."""
    assert _timer_tick(modal_operator, resizing=True) == {"PASS_THROUGH"}
    modal_operator._refreeze_if_resized.assert_not_called()
    modal_operator._maybe_commit.assert_not_called()
    modal_operator._finish.assert_not_called()


def test_the_first_main_loop_tick_refreezes_then_commits(modal_operator):
    order = []
    modal_operator._refreeze_if_resized.side_effect = lambda *_: order.append("refreeze") or True
    modal_operator._maybe_commit.side_effect = lambda *_: order.append("commit")

    assert _timer_tick(modal_operator, resizing=True) == {"PASS_THROUGH"}
    assert _timer_tick(modal_operator, resizing=False) == {"PASS_THROUGH"}
    assert order == ["refreeze", "commit"]


# =============================================================================
# The native side: the flag spans exactly the re-entrant resize dispatch
# =============================================================================

class TestNativeResizeDispatchFlag:
    def test_the_depth_brackets_the_reentrant_dispatch(self):
        text = WM_WINDOW.read_text()
        start = text.index("MACOS and WIN32 don't return to the main-loop while resize.")
        block = text[start:text.index("#endif", start)]
        calls = ["g_mixar_resize_dispatch_depth++",
                 "wm_window_timers_process(C, &dummy_sleep_ms)",
                 "wm_event_do_handlers(C)",
                 "wm_event_do_notifiers(C)",
                 "wm_draw_update(C)",
                 "g_mixar_resize_dispatch_depth--"]
        positions = [block.index(call) for call in calls]
        assert positions == sorted(positions)

    def test_the_flag_reads_the_depth(self):
        text = WM_WINDOW.read_text()
        body = text[text.index("bool Mixar_window_resize_dispatch_active()"):]
        body = body[:body.index("}")]
        assert "g_mixar_resize_dispatch_depth > 0" in body

    def test_python_reads_it_as_a_read_only_window_manager_property(self):
        text = RNA_WM_MIXAR.read_text()
        getter = text[text.index("static bool rna_WindowManager_mixar_window_resizing_get"):]
        assert "return Mixar_window_resize_dispatch_active();" in getter[:200]

        define = text[text.index('"mixar_window_resizing"'):]
        define = define[:define.index("RNA_def_property_ui_text")]
        assert "srna_wm" in text[text.index('"mixar_window_resizing"') - 80:]
        assert '"rna_WindowManager_mixar_window_resizing_get", nullptr' in define
        assert "RNA_def_property_clear_flag(prop, PROP_EDITABLE)" in define

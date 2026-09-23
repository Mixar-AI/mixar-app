# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Toast notifications stay clickable while the agent viewport lock runs.

The lock's input-block modal sits on the window's modal handlers, which
Blender dispatches BEFORE region handlers — so it used to swallow every
LEFTMOUSE over the viewport, including clicks on the toast overlay that
draws there. Toasts became impossible to dismiss or action (e.g. the
"View Queue" button) for the whole duration of an agent turn.

The modal now passes a left-button PRESS through when it lands on a toast
control, so the region's toast UI handler receives it. Applies to every
notification, not just queue ones — the bounds dict is populated for all
visible toasts regardless of source.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import pytest

from mixar.modules.agent_viewport_lock.ui.operators import viewport_block_op as VBO
from mixar.modules.common.notifications import toast_renderer as TR


@pytest.fixture(autouse=True)
def _real_operator(monkeypatch):
    # Root conftest mocks bpy.types.Operator. Compile the actual class body
    # with a plain base so these assertions execute modal logic, not a mock.
    tree = ast.parse(Path(VBO.__file__).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "MIXAR_OT_agent_viewport_block")
    cls.bases = [ast.Name(id="object", ctx=ast.Load())]
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = dict(VBO.__dict__)
    exec(compile(module, VBO.__file__, "exec"), namespace)
    monkeypatch.setattr(VBO, cls.name, namespace[cls.name])
    # Methods read their isolated globals; forward the patchable probe.
    namespace["is_agent_executing"] = lambda: VBO.is_agent_executing()

REGION_PTR = 0xBEEF
# Region sits at (100, 50) in the window; a toast control at region-local
# (500, 400) is therefore at window (600, 450).
REGION_X, REGION_Y = 100, 50
CTRL_X, CTRL_Y = 500, 400
CTRL_W, CTRL_H = 120, 40


def _bounds(close=(), action=(), url=()):
    return {"close": list(close), "action": list(action), "url": list(url)}


@pytest.fixture(autouse=True)
def _clean_bounds():
    TR.toast_bounds_by_region.clear()
    yield
    TR.toast_bounds_by_region.clear()


def _install_action_bounds():
    TR.toast_bounds_by_region[REGION_PTR] = _bounds(
        action=[(
            "nid-1", "mixie.queue_view", None,
            CTRL_X, CTRL_Y, CTRL_W, CTRL_H,
        )],
    )


# ---------------------------------------------------------------------------
# point_in_any_toast_control
# ---------------------------------------------------------------------------


def test_hit_on_action_button():
    _install_action_bounds()
    assert TR.point_in_any_toast_control(REGION_PTR, CTRL_X + 5, CTRL_Y + 5)


def test_hit_on_close_button():
    TR.toast_bounds_by_region[REGION_PTR] = _bounds(
        close=[("nid-1", CTRL_X, CTRL_Y, CTRL_W, CTRL_H)],
    )
    assert TR.point_in_any_toast_control(REGION_PTR, CTRL_X + 1, CTRL_Y + 1)


def test_hit_on_url_link():
    TR.toast_bounds_by_region[REGION_PTR] = _bounds(
        url=[("nid-1", "https://mixar.app", CTRL_X, CTRL_Y, CTRL_W, CTRL_H)],
    )
    assert TR.point_in_any_toast_control(REGION_PTR, CTRL_X + 1, CTRL_Y + 1)


def test_miss_outside_controls():
    _install_action_bounds()
    assert not TR.point_in_any_toast_control(REGION_PTR, 10, 10)


def test_miss_when_region_has_no_toasts():
    assert not TR.point_in_any_toast_control(REGION_PTR, CTRL_X, CTRL_Y)


def test_does_not_mutate_hover_state():
    _install_action_bounds()
    before = TR.toast_hover_state["key"]
    TR.point_in_any_toast_control(REGION_PTR, CTRL_X + 5, CTRL_Y + 5)
    assert TR.toast_hover_state["key"] == before


# ---------------------------------------------------------------------------
# Modal pass-through decision
# ---------------------------------------------------------------------------


class _FakeRegion:
    type = 'WINDOW'

    def __init__(self):
        self.x, self.y = REGION_X, REGION_Y
        self.width, self.height = 1200, 800

    def as_pointer(self):
        return REGION_PTR


def _context_with_view3d(region):
    area = SimpleNamespace(type='VIEW_3D', regions=[region],
                           mixar_moodboard_contains=lambda x, y: False,
                           mixar_header_contains=lambda x, y: False)
    return SimpleNamespace(
        window=SimpleNamespace(screen=SimpleNamespace(areas=[area]), modal_operators={}),
    )


def _event(type='LEFTMOUSE', value='PRESS', on_control=True):
    if on_control:
        mx, my = REGION_X + CTRL_X + 5, REGION_Y + CTRL_Y + 5
    else:
        mx, my = REGION_X + 10, REGION_Y + 10
    return SimpleNamespace(type=type, value=value, mouse_x=mx, mouse_y=my)


def _run_modal(event, monkeypatch, executing=True):
    monkeypatch.setattr(VBO, "is_agent_executing", lambda: executing)
    region = _FakeRegion()
    op = VBO.MIXAR_OT_agent_viewport_block()
    return op.modal(_context_with_view3d(region), event)


def test_click_on_toast_control_passes_through(monkeypatch):
    _install_action_bounds()
    assert _run_modal(_event(), monkeypatch) == {"PASS_THROUGH"}


def test_click_on_empty_viewport_still_blocked(monkeypatch):
    _install_action_bounds()
    assert _run_modal(
        _event(on_control=False), monkeypatch,
    ) == {"RUNNING_MODAL"}


def test_click_blocked_when_no_toasts_visible(monkeypatch):
    assert _run_modal(_event(), monkeypatch) == {"RUNNING_MODAL"}


def test_release_on_toast_control_stays_blocked(monkeypatch):
    # Passing the release too would let Blender synthesize a CLICK that
    # reaches the select keymap — the very thing the lock prevents.
    _install_action_bounds()
    assert _run_modal(
        _event(value='RELEASE'), monkeypatch,
    ) == {"RUNNING_MODAL"}


def test_right_click_on_toast_control_stays_blocked(monkeypatch):
    # The toast handler only acts on LEFTMOUSE press.
    _install_action_bounds()
    assert _run_modal(
        _event(type='RIGHTMOUSE'), monkeypatch,
    ) == {"RUNNING_MODAL"}


def test_edit_hotkey_on_toast_control_stays_blocked(monkeypatch):
    _install_action_bounds()
    assert _run_modal(_event(type='G'), monkeypatch) == {"RUNNING_MODAL"}


def test_hit_test_failure_falls_back_to_blocking(monkeypatch):
    _install_action_bounds()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("bounds unavailable")

    monkeypatch.setattr(TR, "point_in_any_toast_control", _boom)
    assert _run_modal(_event(), monkeypatch) == {"RUNNING_MODAL"}


def test_new_lock_yields_to_existing_read_only_workspace_viewer(monkeypatch):
    monkeypatch.setattr(VBO, "is_agent_executing", lambda: True)
    context = _context_with_view3d(_FakeRegion())
    context.window.modal_operators['VIEW3D_OT_workspace_viewer'] = object()
    op = VBO.MIXAR_OT_agent_viewport_block()
    assert op.modal(context, _event(on_control=False)) == {"PASS_THROUGH"}
    context.window.modal_operators.clear()
    assert op.modal(context, _event(on_control=False)) == {"RUNNING_MODAL"}


@pytest.mark.parametrize("event_type,value", [
    ("LEFTMOUSE", "PRESS"), ("LEFTMOUSE", "RELEASE"),
    ("RIGHTMOUSE", "PRESS"), ("G", "PRESS"), ("X", "PRESS"),
])
@pytest.mark.parametrize("on_board", [True, False])
def test_drawer_input_passes_while_viewport_stays_locked(monkeypatch, event_type, value, on_board):
    monkeypatch.setattr(VBO, "is_agent_executing", lambda: True)
    region = SimpleNamespace(type="WINDOW", x=0, y=0, width=1200, height=800)
    hits = []

    def contains(x, y):
        hits.append((x, y))
        return on_board

    area = SimpleNamespace(type="VIEW_3D", regions=[region], mixar_moodboard_contains=contains,
                           mixar_header_contains=lambda x, y: False)
    context = SimpleNamespace(window=SimpleNamespace(
        screen=SimpleNamespace(areas=[area]), modal_operators={}))
    event = SimpleNamespace(type=event_type, value=value, mouse_x=900, mouse_y=400)
    result = VBO.MIXAR_OT_agent_viewport_block().modal(context, event)
    assert result == ({"PASS_THROUGH"} if on_board else {"RUNNING_MODAL"})
    assert hits == [(900, 400)]


@pytest.mark.parametrize("modal_name", (
    "VIEW3D_OT_moodboard_drawer_grip",
    "MIXIE_OT_moodboard_select_image",
    "MIXIE_OT_moodboard_graph_select",
    "MIXIE_OT_moodboard_frame_select",
    "MIXIE_OT_moodboard_box_select",
))
def test_captured_drag_release_outside_board_reaches_older_modal(monkeypatch, modal_name):
    monkeypatch.setattr(VBO, "is_agent_executing", lambda: True)
    context = _context_with_view3d(_FakeRegion())
    context.window.modal_operators[modal_name] = object()
    op = VBO.MIXAR_OT_agent_viewport_block()
    assert op.modal(context, _event(value='RELEASE', on_control=False)) == {"PASS_THROUGH"}
    for event_type in ('LEFTMOUSE', 'RIGHTMOUSE', 'G'):
        assert op.modal(context, _event(type=event_type, on_control=False)) == {"RUNNING_MODAL"}


def test_armed_mask_tool_does_not_unlock_viewport_mouse_input(monkeypatch):
    monkeypatch.setattr(VBO, "is_agent_executing", lambda: True)
    context = _context_with_view3d(_FakeRegion())
    context.window.modal_operators['MIXIE_OT_moodboard_box_mask_tool'] = object()
    op = VBO.MIXAR_OT_agent_viewport_block()
    for event_type, value in (('LEFTMOUSE', 'RELEASE'), ('LEFTMOUSE', 'PRESS'),
                              ('RIGHTMOUSE', 'PRESS')):
        assert op.modal(context, _event(type=event_type, value=value,
                                       on_control=False)) == {"RUNNING_MODAL"}

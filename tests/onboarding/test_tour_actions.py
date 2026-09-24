# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Interactive tour — app actions under the ``bpy`` mock.

``actions`` talks to the app only through a handful of module functions
(``_call_op``, ``_wm``, ``_zen_view3d_override``, ``_resting_pill_visible``,
``_bubble_windows``…), so these tests swap those for recorders and pin:
the pre-tour snapshot/restore round trip, the demo-image flag-first check,
``pill_supported`` per platform, ``drawer_set`` refusing to fall back to
raw properties, and the Linux (no-pill) island path.
"""

import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

for _name in ("gpu", "gpu.state", "gpu.shader", "gpu.matrix", "gpu.types",
              "gpu_extras", "gpu_extras.batch", "blf", "bgl", "mathutils",
              "addon_utils"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.modules.onboarding.core.tour import actions, actions_state  # noqa: E402


class _Recorder:
    def __init__(self, result=True):
        self.calls = []
        self.result = result

    def __call__(self, path, **kwargs):
        self.calls.append((path, kwargs, actions.suppress_legacy_restart))
        return self.result

    def paths(self):
        return [c[0] for c in self.calls]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    actions.reset_session_state()
    monkeypatch.setattr(actions.bpy.path, "abspath", lambda p: p)
    yield
    actions.reset_session_state()


# --- snapshot / restore -----------------------------------------------------

def test_snapshot_reads_mode_drawer_island_and_tab(monkeypatch):
    wm = SimpleNamespace(mixar_moodboard_drawer_amount=0.0, mixar_bubble_tab="IMAGE")
    monkeypatch.setattr(actions, "get_ui_mode", lambda: "pro")
    monkeypatch.setattr(actions, "_wm", lambda: wm)
    monkeypatch.setattr(actions, "_resting_pill_visible", lambda: True)
    snap = actions.snapshot_state()
    assert snap == {"ui_mode": "pro", "drawer_amount": 0.0,
                    "island": "pill", "bubble_tab": "IMAGE"}


def test_snapshot_island_expanded_then_none(monkeypatch):
    monkeypatch.setattr(actions, "get_ui_mode", lambda: "ai")
    monkeypatch.setattr(actions, "_wm", lambda: None)
    monkeypatch.setattr(actions, "_resting_pill_visible", lambda: False)
    monkeypatch.setattr(actions, "_shown_bubble_windows", lambda: [object()])
    assert actions.snapshot_state()["island"] == "expanded"
    monkeypatch.setattr(actions, "_shown_bubble_windows", lambda: [])
    snap = actions.snapshot_state()
    assert snap["island"] == "none" and snap["drawer_amount"] is None


def test_restore_round_trip_puts_everything_back(monkeypatch):
    ops = _Recorder()
    drawer, tabs = [], []
    monkeypatch.setattr(actions, "_call_op", ops)
    monkeypatch.setattr(actions, "get_ui_mode", lambda: "ai")     # tour left Zen
    monkeypatch.setattr(actions, "drawer_set", lambda a: drawer.append(a) or True)
    monkeypatch.setattr(actions, "island_tab", lambda a: tabs.append(a) or True)
    monkeypatch.setattr(actions, "pill_supported", lambda: True)
    monkeypatch.setattr(actions, "_bubble_windows", lambda: [object()])
    snap = {"ui_mode": "pro", "drawer_amount": 0.0, "island": "pill",
            "bubble_tab": "IMAGE"}
    assert actions.restore_state(snap) is True
    # Mode switch runs under the legacy-restart suppression.
    assert ("mixar.set_ui_mode_pro", {}, True) in ops.calls
    assert "mixar.bubble_minimise" in ops.paths()
    assert drawer == [{"amount": 0.0}]
    assert tabs == [{"tab": "IMAGE"}]
    assert actions.suppress_legacy_restart is False


def test_restore_expanded_and_none(monkeypatch):
    expands = []
    monkeypatch.setattr(actions, "get_ui_mode", lambda: "ai")
    monkeypatch.setattr(actions, "island_expand", lambda a: expands.append(a) or True)
    assert actions.restore_state({"ui_mode": "ai", "island": "expanded"}) is True
    assert expands == [{}]
    # "none" leaves the island alone and nothing else is touched.
    calls = _Recorder()
    monkeypatch.setattr(actions, "_call_op", calls)
    assert actions.restore_state({"ui_mode": "ai", "island": "none"}) is True
    assert calls.calls == []


def test_restore_reports_false_but_keeps_going(monkeypatch):
    tabs = []
    monkeypatch.setattr(actions, "get_ui_mode", lambda: "ai")
    monkeypatch.setattr(actions, "drawer_set", lambda a: False)
    monkeypatch.setattr(actions, "island_tab", lambda a: tabs.append(a) or True)
    ok = actions.restore_state({"ui_mode": "ai", "drawer_amount": 1.0,
                                "island": "none", "bubble_tab": "AGENT"})
    assert ok is False and tabs == [{"tab": "AGENT"}]


def test_restore_never_raises(monkeypatch):
    def boom(_snapshot):
        raise RuntimeError("nope")
    monkeypatch.setattr(actions_state, "restore_state", boom)
    assert actions.restore_state({"ui_mode": "ai"}) is False


def test_tour_cleanup_leaves_drawer_open(monkeypatch):
    drawer, tabs = [], []
    monkeypatch.setattr(actions, "drawer_set", lambda a: drawer.append(a) or True)
    monkeypatch.setattr(actions, "island_tab", lambda a: tabs.append(a) or True)
    monkeypatch.setattr(actions, "ensure_zen", lambda a: True)
    assert actions.tour_cleanup({}) is True
    assert drawer == [] and tabs == [{"tab": "AGENT"}]


# --- demo image -------------------------------------------------------------

def _item(flag=None, name="", filepath=""):
    props = {actions.DEMO_ITEM_FLAG: flag} if flag is not None else {}
    image = SimpleNamespace(name=name, filepath=filepath) if name or filepath else None
    return SimpleNamespace(get=props.get, image=image)


def test_board_has_image_flag_first_then_filepath(tmp_path):
    demo = str(tmp_path / "demo_concept.png")
    other = str(tmp_path / "elsewhere" / "demo_concept.png")
    scene = SimpleNamespace(mixie_moodboard_images=[_item(flag=True)])
    assert actions._board_has_image(scene, demo) is True
    # Same basename in another folder no longer counts.
    scene = SimpleNamespace(mixie_moodboard_images=[_item(name="demo_concept.png",
                                                          filepath=other)])
    assert actions._board_has_image(scene, demo) is False
    scene = SimpleNamespace(mixie_moodboard_images=[_item(name="x", filepath=demo)])
    assert actions._board_has_image(scene, demo) is True
    assert actions._board_has_image(SimpleNamespace(), demo) is False


def test_add_demo_image_stamps_flag(monkeypatch, tmp_path):
    demo = tmp_path / "demo_concept.png"
    demo.write_bytes(b"png")
    stamped = {}

    class Item:
        def __setitem__(self, key, value):
            stamped[key] = value

    fake = SimpleNamespace(load_media_file_to_board=lambda scene, path: Item())
    monkeypatch.setitem(sys.modules, "mixar.modules.moodboard.core.media_import", fake)
    monkeypatch.setattr(actions.config, "demo_image_path", lambda: str(demo))
    monkeypatch.setattr(actions, "_scene", lambda: SimpleNamespace(
        mixie_moodboard_images=[]))
    assert actions.moodboard_add_demo_image({}) is True
    assert stamped == {actions.DEMO_ITEM_FLAG: True}


# --- platform ---------------------------------------------------------------

@pytest.mark.parametrize("platform, expected", [
    ("darwin", True), ("win32", True), ("linux", False), ("freebsd14", False),
])
def test_pill_supported_by_platform(monkeypatch, platform, expected):
    monkeypatch.setattr(actions.sys, "platform", platform)
    assert actions.pill_supported() is expected


def test_island_open_without_pill_opens_expanded(monkeypatch):
    ops = _Recorder()
    monkeypatch.setattr(actions, "_call_op", ops)
    monkeypatch.setattr(actions, "pill_supported", lambda: False)
    monkeypatch.setattr(actions, "_resting_pill_visible", lambda: False)
    assert actions.island_open({}) is True
    assert ops.paths() == ["mixar.agent_bubble_open_window"]
    assert actions._island_opened_at > 0.0


def test_island_expanded_without_pill_once_window_shown(monkeypatch):
    monkeypatch.setattr(actions, "pill_supported", lambda: False)
    monkeypatch.setattr(actions, "_shown_bubble_windows", lambda: [])
    actions._island_opened_at = time.monotonic() - actions.ISLAND_OPEN_SETTLE_S - 1
    assert actions.check("island_expanded", {}) is False
    monkeypatch.setattr(actions, "_shown_bubble_windows", lambda: [object()])
    assert actions.check("island_expanded", {}) is True


def test_island_open_early_return_still_stamps(monkeypatch):
    monkeypatch.setattr(actions, "_resting_pill_visible", lambda: True)
    actions._pill_seen_since_open = True
    before = time.monotonic()
    assert actions.island_open({}) is True
    assert actions._island_opened_at >= before
    assert actions._pill_seen_since_open is False


def test_reset_session_state():
    actions._island_opened_at = 5.0
    actions._pill_seen_since_open = True
    actions._warned_predicates.add("x")
    actions.reset_session_state()
    assert actions._island_opened_at == float("-inf")
    assert actions._pill_seen_since_open is False
    assert not actions._warned_predicates


# --- drawer -----------------------------------------------------------------

def test_drawer_set_returns_false_without_override_and_never_pokes_wm(monkeypatch):
    wm = SimpleNamespace(mixar_moodboard_drawer_amount=0.25,
                         mixar_moodboard_drawer_target=0)
    monkeypatch.setattr(actions, "_wm", lambda: wm)
    monkeypatch.setattr(actions, "_zen_view3d_override", lambda: None)
    assert actions.drawer_set({"amount": 1.0}) is False
    assert (wm.mixar_moodboard_drawer_amount, wm.mixar_moodboard_drawer_target) == (0.25, 0)


def test_drawer_set_returns_false_when_operator_fails(monkeypatch):
    ops = _Recorder(result=False)
    monkeypatch.setattr(actions, "_call_op", ops)
    monkeypatch.setattr(actions, "_zen_view3d_override", lambda: {"window": object()})
    assert actions.drawer_set({"amount": 1.0}) is False
    assert ops.calls[0][0] == "view3d.moodboard_drawer_set"
    assert ops.calls[0][1] == {"amount": 1.0, "target": 1.0}
    assert actions.drawer_set({"amount": "bad"}) is False

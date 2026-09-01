# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""agent_ui driver: query matching, click-point occlusion, event sequences,
denylist, the ui.wait DSL and drag endpoint resolution — all without Blender."""

import sys
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.agent_ui import driver as drv  # noqa: E402
from mixar.modules.agent_ui.constants import (  # noqa: E402
    ERR_DENIED,
    ERR_INVALID_PARAMS,
    ERR_NO_MATCH,
    ERR_TIMEOUT,
)
from mixar.modules.agent_ui.errors import UIControlError  # noqa: E402

from agent_ui_fakes import simple_layout, widget  # noqa: E402


def run(gen):
    """Step a driver generator to completion; return its result."""
    try:
        while True:
            delay = next(gen)
            assert delay >= 0
    except StopIteration as stop:
        return stop.value


@pytest.fixture
def layout(monkeypatch):
    wm, win, area, ui_region, win_region, widgets = simple_layout()
    monkeypatch.setattr(drv, "_wm", lambda: wm)
    monkeypatch.setattr(drv, "FIND_RETRY_WINDOW_S", 0.01)
    drv.reset_runtime_state()
    return wm, win, area, ui_region, win_region, widgets


def test_snapshot_annotates_area_region_center_and_blanks_secrets(layout):
    wm, win, area, ui_region, win_region, widgets = layout
    widgets.append(widget(win, area, ui_region, "Generate", rect=(700, 100, 900, 130),
                          op="MIXIE_OT_imagegen_generate"))
    widgets.append(widget(win, area, ui_region, "sk-live-123", rect=(700, 200, 900, 230),
                          type="Text", prop="byok_api_key", value="sk-live-123"))
    snap = drv.snapshot()
    gen = next(w for w in snap if w.get("op") == "MIXIE_OT_imagegen_generate")
    assert gen["area_type"] == "MIXIE" and gen["region_type"] == "UI"
    assert gen["center"] == [800, 115] and gen["window"] == win.as_pointer()
    secret = next(w for w in snap if w.get("prop") == "byok_api_key")
    assert secret["text"] == "" and secret["value"] == ""
    public = drv.public_widget(gen)
    assert not any(k.startswith("_") for k in public)


def test_find_exact_contains_and_ambiguity_ordering(layout):
    wm, win, area, ui_region, win_region, widgets = layout
    widgets.append(widget(win, area, ui_region, "Image Gen", rect=(0, 0, 50, 10), enabled=False))
    widgets.append(widget(win, area, ui_region, "Image Gen", rect=(0, 0, 200, 40)))
    widgets.append(widget(win, area, ui_region, "Image Generator settings", rect=(0, 0, 10, 10),
                          tip="opens Image Gen"))
    assert len(drv.find(text="image gen")) == 2  # exact: label or tooltip, case-insensitive
    assert len(drv.find(text="Image Gen", contains=True)) == 3  # substring reaches the tooltip
    best = drv.find_one(text="Image Gen")
    assert best["enabled"] is True and best["rect"] == [0, 0, 200, 40]
    with pytest.raises(UIControlError) as exc:
        drv.find_one(text="nope")
    assert exc.value.code == ERR_NO_MATCH


def test_pick_click_point_avoids_floating_sidebar(layout):
    wm, win, area, ui_region, win_region, widgets = layout
    # Canvas card whose center (750, 400) sits under the UI sidebar (x>=700).
    widgets.append(widget(win, area, win_region, "card", rect=(500, 300, 1000, 500),
                          type="Custom", surface="moodboard_media"))
    w = drv.snapshot()[0]
    x, y = drv.pick_click_point(w)
    assert 500 <= x < 700 and 300 <= y <= 500


def test_click_steps_sequence_warps_in_mixed_mode(layout):
    wm, win, area, ui_region, win_region, widgets = layout
    widgets.append(widget(win, area, ui_region, "Go", rect=(700, 100, 900, 130)))
    w = drv.snapshot()[0]
    run(drv.click_steps(w))
    types_ = [(e["type"], e["value"]) for e in win.events]
    assert types_ == [("MOUSEMOVE", "NOTHING"), ("MOUSEMOVE", "NOTHING"),
                      ("LEFTMOUSE", "PRESS"), ("LEFTMOUSE", "RELEASE")]
    assert win.events[-1]["x"] == 800 and win.events[-1]["y"] == 115
    assert win.warps[-1] == (800, 115)


def test_no_cursor_warp_under_event_simulate(layout, monkeypatch):
    wm, win, area, ui_region, win_region, widgets = layout
    monkeypatch.setattr(drv, "event_simulate_mode", lambda: True)
    widgets.append(widget(win, area, ui_region, "Go", rect=(700, 100, 900, 130)))
    run(drv.click_steps(drv.snapshot()[0]))
    assert win.warps == [] and len(win.events) == 4


def test_denied_operator_and_key_combo(layout):
    wm, win, area, ui_region, win_region, widgets = layout
    widgets.append(widget(win, area, ui_region, "Quit", rect=(0, 0, 10, 10), op="wm.quit_blender"))
    with pytest.raises(UIControlError) as exc:
        run(drv.click_steps(drv.snapshot()[0]))
    assert exc.value.code == ERR_DENIED and win.events == []
    with pytest.raises(UIControlError) as exc:
        drv.press(win, "Q", oskey=True)
    assert exc.value.code == ERR_DENIED
    drv.press(win, "RET")
    assert [e["type"] for e in win.events] == ["RET", "RET"]
    with pytest.raises(UIControlError) as exc:
        drv.type_text(win, "héllo")
    assert exc.value.code == ERR_INVALID_PARAMS and len(win.events) == 2  # nothing typed


def test_key_events_carry_last_pointer_position(layout):
    wm, win, area, ui_region, win_region, widgets = layout
    drv.move_to(win, 123, 456)
    drv.press(win, "F")
    assert win.events[-1]["x"] == 123 and win.events[-1]["y"] == 456


def test_wait_until_dsl(layout):
    wm, win, area, ui_region, win_region, widgets = layout
    widgets.append(widget(win, area, ui_region, "Ready", rect=(0, 0, 10, 10), sel=True))
    assert run(drv.wait_until({"widget_present": {"text": "Ready"}}, 1))["seconds"] >= 0
    assert run(drv.wait_until({"widget_sel": {"query": {"text": "Ready"}, "sel": True}}, 1))
    assert run(drv.wait_until({"chat_state": "busy"}, 1))
    with pytest.raises(UIControlError) as exc:
        run(drv.wait_until({"widget_absent": {"text": "Ready"}}, 0.02))
    assert exc.value.code == ERR_TIMEOUT
    for bad in ({"eval": "1"}, {}, "x", {"widget_sel": "x"}):
        with pytest.raises(UIControlError) as exc:
            run(drv.wait_until(bad, 1))
        assert exc.value.code == ERR_INVALID_PARAMS


def test_drag_relative_endpoint_and_stability(layout):
    wm, win, area, ui_region, win_region, widgets = layout
    widgets.append(widget(win, area, win_region, "n1", rect=(100, 100, 200, 200),
                          type="Custom", surface="moodboard_output"))
    result = run(drv.drag({"surface": "moodboard_output"}, {"dx": 300, "dy": -50}, steps=4))
    presses = [e for e in win.events if e["value"] == "PRESS"]
    releases = [e for e in win.events if e["value"] == "RELEASE"]
    assert presses[0]["x"] == 150 and presses[0]["y"] == 150
    assert releases[0]["x"] == 450 and releases[0]["y"] == 100
    assert result["from"] == [150, 150] and result["to"] == [450, 100]
    assert result["from_widget"]["surface"] == "moodboard_output" and result["to_widget"] is None
    with pytest.raises(UIControlError) as exc:
        run(drv.drag({"dx": 1, "dy": 1}, {"dx": 1, "dy": 1}))
    assert exc.value.code == ERR_INVALID_PARAMS


def test_choose_and_set_text_flows(layout):
    wm, win, area, ui_region, win_region, widgets = layout
    widgets.append(widget(win, area, ui_region, "1:1", rect=(700, 300, 900, 330),
                          type="Menu", prop="p_aspect_ratio"))
    popup_item = widget(win, None, None, "16:9", rect=(700, 250, 900, 280), popup=True)

    original_click = drv.click_steps

    def click_then_popup(w, double=False):
        result = yield from original_click(w, double)
        if w.get("prop") == "p_aspect_ratio" and popup_item not in widgets:
            widgets.append(popup_item)
        return result

    drv.click_steps = click_then_popup
    try:
        out = run(drv.choose({"prop": "p_aspect_ratio"}, "16:9"))
    finally:
        drv.click_steps = original_click
    assert out["chose"] == "16:9" and out["widget"]["prop"] == "p_aspect_ratio"
    presses = [e for e in win.events if e["value"] == "PRESS" and e["type"] == "LEFTMOUSE"]
    assert len(presses) == 2 and presses[1]["y"] == 265

    win.events.clear()
    widgets.append(widget(win, area, ui_region, "", rect=(700, 400, 900, 430),
                          type="Text", prop="prompt", region_type="UI"))
    out = run(drv.set_text({"prop": "prompt"}, "Hi 2", enter=True))
    assert out["typed"] == "Hi 2"
    keys = [e["type"] for e in win.events if e["type"] not in ("MOUSEMOVE", "LEFTMOUSE")]
    assert keys[:4] == ["A", "A", "BACK_SPACE", "BACK_SPACE"]
    assert keys[4:] == ["H", "H", "I", "I", "SPACE", "SPACE", "TWO", "TWO", "RET", "RET"]
    assert [e for e in win.events if e["type"] == "H"][0]["shift"] is True

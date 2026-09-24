# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Interactive tour — anchor resolution against a fake QA dump.

``anchors`` reads the app through three small module functions
(``_read_dump``, ``_area_types_by_ptr``, ``_windows``) precisely so these
tests can feed it a canned widget dump and fake RNA windows under the
``bpy`` mock. Field names in the dump below match
``interface_qa_inspect.cc`` (``w``/``a``/``at``/``r``/``rt``/``type``/
``text``/``tip``/``op``/``prop``/``surface``/``value``/``popup``/``rect``).
"""

import json
import sys
from unittest.mock import MagicMock

import pytest

for _name in ("gpu", "gpu.state", "gpu.shader", "gpu.matrix", "gpu.types",
              "gpu_extras", "gpu_extras.batch", "blf", "bgl", "mathutils",
              "addon_utils"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.modules.onboarding.core.tour import anchors  # noqa: E402
from mixar.modules.onboarding.core.tour.anchors import AnchorRect  # noqa: E402

MAIN_WIN = 1001
BUBBLE_WIN = 2002
VIEW3D_AREA = 11
BUBBLE_AREA = 22
POPUP_WIN = MAIN_WIN

AREA_TYPES = {VIEW3D_AREA: "VIEW_3D", BUBBLE_AREA: "AGENT_BUBBLE"}


def _widget(**fields):
    base = {"w": MAIN_WIN, "a": VIEW3D_AREA, "at": 1, "r": 5, "rt": 0,
            "type": "But", "text": "", "rect": [0, 0, 10, 10], "enabled": True}
    base.update(fields)
    return base


DUMP = {
    "windows": [{"ptr": MAIN_WIN, "size": [1600, 900]},
                {"ptr": BUBBLE_WIN, "size": [678, 230]}],
    "widgets": [
        # Two Agent-tab candidates: the bubble's (larger) and a stray one
        # in the main window with the same op+tip.
        _widget(w=str(BUBBLE_WIN), a=str(BUBBLE_AREA), at=42, type="Tab",
                text="Agent", tip="Agent chat", op="wm.context_set_enum",
                rect=[100, 180, 160, 204]),
        _widget(w=MAIN_WIN, a=VIEW3D_AREA, type="Tab", text="Agent",
                tip="Agent chat", op="wm.context_set_enum", rect=[0, 0, 20, 20]),
        # A popup copy that must be ignored unless asked for.
        _widget(w=POPUP_WIN, a=0, popup=True, type="Tab", text="Agent",
                tip="Agent chat", op="wm.context_set_enum", rect=[0, 0, 500, 500]),
        # Sidebar category tabs as custom-surface targets.
        _widget(type="Custom", surface="panel_tab", text="Image Gen",
                rect=[1500, 600, 1540, 680], sel=True),
        _widget(type="Custom", surface="panel_tab", text="Model Gen",
                rect=[1500, 500, 1540, 580]),
        # Same surface+text twice: largest must win.
        _widget(type="Custom", surface="moodboard_drawer_grip", text="",
                rect=[1580, 300, 1590, 320]),
        _widget(type="Custom", surface="moodboard_drawer_grip", text="",
                rect=[1570, 250, 1600, 400]),
        # Degenerate rect: skipped.
        _widget(type="Custom", surface="pill_cat", text="Mixie",
                value="Idle", rect=[10, 10, 10, 30]),
        # Composer prop in the bubble.
        _widget(w=BUBBLE_WIN, a=BUBBLE_AREA, type="Text",
                prop="mixie_chat_input", rect=[20, 20, 600, 60]),
    ],
}


@pytest.fixture
def dump(monkeypatch):
    monkeypatch.setattr(anchors, "_read_dump", lambda: json.dumps(DUMP))
    monkeypatch.setattr(anchors, "_area_types_by_ptr", lambda: dict(AREA_TYPES))
    return DUMP


# --- normalize_ptr ----------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (123, 123), ("123", 123), (" 456 ", 456), ("0x1f", 31), ("0X10", 16),
    (7.0, 7), (0, 0), ("0", 0),
    (None, None), ("", None), ("abc", None), (-1, None), ("-5", None),
    (True, None), (7.5, None), ([1], None),
])
def test_normalize_ptr(value, expected):
    assert anchors.normalize_ptr(value) == expected


# --- AnchorRect -------------------------------------------------------------

def test_anchor_rect_geometry():
    r = AnchorRect(1, 10, 20, 30, 60)
    assert r.width == 20 and r.height == 40
    assert r.center == (20, 40)
    assert r.contains(10, 20) and r.contains(30, 60) and r.contains(20, 40)
    assert not r.contains(9.9, 40) and not r.contains(20, 60.1)
    p = r.padded(5)
    assert (p.xmin, p.ymin, p.xmax, p.ymax) == (5, 15, 35, 65)
    assert p.window_ptr == 1 and r.contains(10, 20)  # original untouched


# --- widget specs -----------------------------------------------------------

def test_resolve_by_op_and_tip_with_area_filter(dump):
    rect = anchors.resolve({"op": "wm.context_set_enum", "tip": "Agent chat",
                            "area": "AGENT_BUBBLE"})
    assert rect == AnchorRect(BUBBLE_WIN, 100, 180, 160, 204)


def test_resolve_area_filter_excludes_other_areas(dump):
    rect = anchors.resolve({"op": "wm.context_set_enum", "tip": "Agent chat",
                            "area": "VIEW_3D"})
    assert rect == AnchorRect(MAIN_WIN, 0, 0, 20, 20)


def test_resolve_without_area_picks_largest_non_popup(dump):
    rect = anchors.resolve({"op": "wm.context_set_enum", "tip": "Agent chat"})
    assert rect.window_ptr == BUBBLE_WIN and rect.width == 60


def test_popup_widgets_are_skipped_unless_requested(dump):
    rect = anchors.resolve({"op": "wm.context_set_enum", "tip": "Agent chat",
                            "popup": True})
    assert rect == AnchorRect(POPUP_WIN, 0, 0, 500, 500)


def test_resolve_by_surface_and_text(dump):
    rect = anchors.resolve({"surface": "panel_tab", "text": "Model Gen"})
    assert rect == AnchorRect(MAIN_WIN, 1500, 500, 1540, 580)


def test_largest_match_wins(dump):
    rect = anchors.resolve({"surface": "moodboard_drawer_grip"})
    assert (rect.xmin, rect.ymin, rect.xmax, rect.ymax) == (1570, 250, 1600, 400)


def test_zero_size_rects_are_skipped(dump):
    assert anchors.resolve({"surface": "pill_cat"}) is None


def test_resolve_by_prop(dump):
    rect = anchors.resolve({"prop": "mixie_chat_input", "area": "AGENT_BUBBLE"})
    assert rect.window_ptr == BUBBLE_WIN and rect.height == 40


def test_missing_and_bad_specs_resolve_to_none(dump):
    assert anchors.resolve({"op": "nope.nothing"}) is None
    assert anchors.resolve({}) is None
    assert anchors.resolve(None) is None
    assert anchors.resolve({"bogus": 1}) is None


def test_invalid_dump_json_is_not_fatal(monkeypatch):
    monkeypatch.setattr(anchors, "_read_dump", lambda: "{not json")
    monkeypatch.setattr(anchors, "_area_types_by_ptr", dict)
    assert anchors.resolve({"surface": "panel_tab"}) is None


# --- region / window specs (fake RNA) ---------------------------------------

class _Region:
    def __init__(self, type_, x, y, w, h):
        self.type, self.x, self.y, self.width, self.height = type_, x, y, w, h


class _Area:
    def __init__(self, ptr, type_, regions):
        self._ptr, self.type, self.regions = ptr, type_, regions

    def as_pointer(self):
        return self._ptr


class _Window:
    def __init__(self, ptr, w, h, areas):
        self._ptr, self.width, self.height = ptr, w, h
        self.screen = MagicMock()
        self.screen.areas = areas

    def as_pointer(self):
        return self._ptr


def _fake_windows():
    main = _Window(MAIN_WIN, 1600, 900, [
        _Area(VIEW3D_AREA, "VIEW_3D", [_Region("HEADER", 0, 870, 1600, 30),
                                       _Region("WINDOW", 0, 0, 1600, 870)]),
    ])
    bubble = _Window(BUBBLE_WIN, 678, 230, [
        _Area(BUBBLE_AREA, "AGENT_BUBBLE", [_Region("HEADER", 0, 200, 678, 30),
                                            _Region("WINDOW", 0, 40, 678, 160),
                                            _Region("TOOLS", 0, 0, 678, 40)]),
    ])
    small = _Window(3003, 300, 200, [
        _Area(33, "PROPERTIES", [_Region("WINDOW", 0, 0, 300, 200)]),
    ])
    return [bubble, small, main]


@pytest.fixture
def rna(monkeypatch):
    monkeypatch.setattr(anchors, "_windows", _fake_windows)
    monkeypatch.setattr(anchors, "_read_dump", lambda: "")


def test_main_window_is_largest_without_bubble(rna):
    assert anchors.main_window().as_pointer() == MAIN_WIN
    assert anchors.window_by_ptr(str(BUBBLE_WIN)).as_pointer() == BUBBLE_WIN
    assert anchors.window_by_ptr(999) is None


def test_host_region_is_main_view3d_window_region(rna):
    window, area, region = anchors.host_region()
    assert window.as_pointer() == MAIN_WIN and area.type == "VIEW_3D"
    assert region.type == "WINDOW" and region.height == 870


def test_region_spec_resolves_through_rna(rna):
    assert anchors.resolve({"area": "VIEW_3D", "region": "WINDOW"}) == \
        AnchorRect(MAIN_WIN, 0, 0, 1600, 870)
    assert anchors.resolve({"area": "AGENT_BUBBLE", "region": "TOOLS"}) == \
        AnchorRect(BUBBLE_WIN, 0, 0, 678, 40)
    assert anchors.resolve({"area": "NODE_EDITOR"}) is None


def test_window_area_spec_is_union_of_regions(rna):
    assert anchors.resolve({"window_area": "AGENT_BUBBLE"}) == \
        AnchorRect(BUBBLE_WIN, 0, 0, 678, 230)
    assert anchors.window_rect(_fake_windows()[2]) == AnchorRect(MAIN_WIN, 0, 0, 1600, 900)


# --- AnchorCache ------------------------------------------------------------

def test_cache_reads_dump_once_per_ttl_and_retries_none(monkeypatch):
    reads = []
    payload = {"widgets": []}

    def read():
        reads.append(1)
        return json.dumps(payload)

    monkeypatch.setattr(anchors, "_read_dump", read)
    monkeypatch.setattr(anchors, "_area_types_by_ptr", dict)
    clock = [0.0]
    cache = anchors.AnchorCache(ttl_s=0.5, now=lambda: clock[0])
    spec = {"surface": "panel_tab", "text": "Image Gen"}

    assert cache.get(spec) is None
    assert cache.get({"surface": "moodboard_drawer_grip"}) is None
    assert cache.get(spec) is None
    assert len(reads) == 1                      # one dump shared by all specs

    payload["widgets"].append(_widget(type="Custom", surface="panel_tab",
                                      text="Image Gen", rect=[1, 1, 5, 5]))
    clock[0] = 0.4
    assert cache.get(spec) is None              # still within ttl: cached None
    clock[0] = 0.6
    assert cache.get(spec) == AnchorRect(MAIN_WIN, 1, 1, 5, 5)
    assert len(reads) == 2

    cache.invalidate()
    assert cache.get(spec) is not None and len(reads) == 3

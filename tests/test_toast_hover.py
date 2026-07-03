# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for toast hover/pressed hit-test logic (toast_renderer)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

# toast_renderer pulls in blf and gpu drawing primitives at import time
for _name in ("blf", "gpu", "gpu.state", "gpu.shader", "gpu_extras", "gpu_extras.batch"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.modules.common.notifications import toast_renderer as tr


REGION = 12345


def _setup_bounds():
    tr.toast_bounds_by_region.clear()
    tr.toast_hover_state["key"] = None
    tr.toast_pressed_state["key"] = None
    tr.toast_bounds_by_region[REGION] = {
        # (nid, x, y, w, h)
        "close": [("n1", 480, 260, 30, 30)],
        # (nid, operator, x, y, w, h)
        "action": [
            ("n1", "mixar.dismiss_update", 300, 100, 80, 38),
            ("n1", "mixar.install_update", 390, 100, 120, 38),
        ],
        # (nid, url, x, y, w, h)
        "url": [("n1", "https://example.com", 60, 180, 400, 20)],
    }


def test_hover_action_button_sets_key_and_reports_change():
    _setup_bounds()
    changed = tr.update_hover_state(REGION, 400, 110)
    assert changed is True
    assert tr.toast_hover_state["key"] == ("action", "n1", "mixar.install_update")


def test_hover_same_target_reports_no_change():
    _setup_bounds()
    assert tr.update_hover_state(REGION, 400, 110) is True
    assert tr.update_hover_state(REGION, 410, 120) is False
    assert tr.toast_hover_state["key"] == ("action", "n1", "mixar.install_update")


def test_hover_off_clears_key():
    _setup_bounds()
    tr.update_hover_state(REGION, 400, 110)
    changed = tr.update_hover_state(REGION, 10, 10)
    assert changed is True
    assert tr.toast_hover_state["key"] is None


def test_hover_close_button_takes_priority():
    _setup_bounds()
    tr.update_hover_state(REGION, 490, 270)
    assert tr.toast_hover_state["key"] == ("close", "n1")


def test_hover_url():
    _setup_bounds()
    tr.update_hover_state(REGION, 100, 190)
    assert tr.toast_hover_state["key"] == ("url", "n1")


def test_hover_unknown_region_clears_key():
    _setup_bounds()
    tr.update_hover_state(REGION, 400, 110)
    assert tr.update_hover_state(99999, 400, 110) is True
    assert tr.toast_hover_state["key"] is None


def test_adjacent_buttons_resolve_distinctly():
    _setup_bounds()
    tr.update_hover_state(REGION, 310, 110)
    assert tr.toast_hover_state["key"] == ("action", "n1", "mixar.dismiss_update")
    tr.update_hover_state(REGION, 395, 110)
    assert tr.toast_hover_state["key"] == ("action", "n1", "mixar.install_update")


def test_point_in_rect_edges_inclusive():
    assert tr.point_in_rect(300, 100, 300, 100, 80, 38)
    assert tr.point_in_rect(380, 138, 300, 100, 80, 38)
    assert not tr.point_in_rect(381, 110, 300, 100, 80, 38)

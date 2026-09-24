# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Interactive tour — the resting pill's footprint in host-window pixels.

``Window.mixar_content_rect_in`` reports in the platform's native unit:
points on macOS (where ``Window.width`` is points too) but DPI-scaled
logical units on Windows (where ``Window.width`` is pixels). The ring,
hint and cursor around the pill must land on it in both, so the result is
scaled against the host measured with the same call, never ``host.width``.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

for _name in ("gpu", "gpu.state", "gpu.shader", "gpu.matrix", "gpu.types",
              "gpu_extras", "gpu_extras.batch", "blf", "bgl", "mathutils",
              "addon_utils"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.modules.onboarding.core.tour import anchors, anchors_windows  # noqa: E402
from mixar.modules.onboarding.core.tour.anchors import AnchorRect  # noqa: E402

MAIN_WIN = 1001
PILL_WIN = 2002


class _Region:
    type = "WINDOW"

    def __init__(self, w, h):
        self.x, self.y, self.width, self.height = 0, 0, w, h


class _Window:
    """``native`` maps a window to its native content rect in the host's
    client coordinates, in that platform's unit."""

    def __init__(self, ptr, w, h, area_type, native):
        self._ptr, self.width, self.height = ptr, w, h
        self.x = self.y = 0
        self._native = native
        area = SimpleNamespace(type=area_type, regions=[_Region(*native["px"])])
        self.screen = SimpleNamespace(areas=[area])

    def as_pointer(self):
        return self._ptr

    def mixar_content_rect_in(self, host):
        return self._native["rect"]


def _setup(monkeypatch, host_width, host_native, pill_native):
    host = _Window(MAIN_WIN, host_width, 1050, "VIEW_3D", host_native)
    pill = _Window(PILL_WIN, 380, 55, "AGENT_BUBBLE", pill_native)
    monkeypatch.setattr(anchors, "_windows", lambda: [host, pill])
    monkeypatch.setattr(anchors, "_read_dump", lambda: "")
    snapshot = SimpleNamespace(widgets=[{"surface": "pill_cat", "w": PILL_WIN}])
    return host, pill, snapshot


def test_windows_dpi_scaled_content_rect_lands_on_the_pill(monkeypatch):
    # 125 % display scaling: Window.width is pixels, the native call is /1.25.
    host, pill, snap = _setup(
        monkeypatch, 1680,
        {"px": (1680, 1050), "rect": (0, 0, 1344, 840)},
        {"px": (380, 55), "rect": (518, 53, 304, 44)})
    assert anchors_windows._live_offset_and_size(pill, host) == \
        pytest.approx((647.5, 66.25, 380.0, 55.0))
    assert anchors_windows.resolve_pill_on_host({"pill_on_host": True}, snap) == \
        AnchorRect(MAIN_WIN, 647.5, 66.25, 1027.5, 121.25)


def test_macos_points_scale_to_retina_pixels(monkeypatch):
    # Retina: Window.width is points (840), regions and the ring are pixels.
    host, pill, snap = _setup(
        monkeypatch, 840,
        {"px": (1680, 1050), "rect": (0, 0, 840, 525)},
        {"px": (760, 110), "rect": (324, 33, 190, 27)})
    assert anchors_windows.resolve_pill_on_host({"pill_on_host": True}, snap) == \
        AnchorRect(MAIN_WIN, 648.0, 66.0, 1028.0, 120.0)

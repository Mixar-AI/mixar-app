# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent-working halo is painted natively from the View3D overlay pass.

The Python POST_PIXEL painter needed a full viewport redraw per frame, so the
breathing animation re-rendered the scene through EEVEE ~18 times a second
for the whole turn. The native painter (view3d_agent_halo.cc) draws from
`draw_overlay`, advanced by cursor redraws, and the Python side only mirrors
state into WindowManager ID properties.
"""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
V3D = ROOT / "src/source/blender/editors/space_view3d"
HALO_CC = V3D / "view3d_agent_halo.cc"


def test_native_painter_is_wired_into_the_overlay_pass_and_the_build():
    cc = HALO_CC.read_text()
    # A window repaint, not only a region cursor tag: Blender's window-redraw
    # test ignores the region flag for editor regions, so the halo froze (3.15).
    body = cc[cc.index("static wmOperatorStatus agent_halo_redraw_exec("):]
    body = body[:body.index("\n}\n")]
    assert "WM_paint_cursor_tag_redraw(&win, region)" in body
    assert "ED_region_tag_redraw(" not in body          # never a full viewport re-render
    assert "MIXAR_OT_agent_halo_redraw" in cc and "OPTYPE_INTERNAL" in cc
    assert "view3d_agent_halo_overlay_draw(C, region);" in (V3D / "view3d_director_overlay.cc").read_text()
    assert "view3d_agent_halo.cc" in (V3D / "CMakeLists.txt").read_text()
    assert "WM_operatortype_append(MIXAR_OT_agent_halo_redraw)" in (V3D / "view3d_director_nudge.cc").read_text()


def test_native_constants_match_the_python_constants():
    from mixar.modules.agent_viewport_lock import constants as C
    cc = HALO_CC.read_text()
    def num(name):
        return float(re.search(rf"{name}\s*=\s*([0-9.]+)f?;", cc).group(1))
    assert num("HALO_BAND_PX") == C.HALO_BAND
    assert num("HALO_ALPHA_MIN") == C.HALO_ALPHA_MIN
    assert num("HALO_ALPHA_MAX") == C.HALO_ALPHA_MAX
    assert num("HALO_PERIOD_S") == C.HALO_PERIOD_S
    assert num("HALO_FALLOFF_EXP") == C.HALO_FALLOFF_EXP
    assert int(num("HALO_STEPS")) == C.HALO_STEPS
    assert f'"{C.HALO_ACTIVE_WM_PROP}"' in cc and f'"{C.HALO_INSET_WM_PROP}"' in cc
    color = re.search(r"HALO_COLOR\[3\] = \{([^}]+)\}", cc).group(1)
    assert tuple(float(v.strip().rstrip("f")) for v in color.split(",")) == C.HALO_COLOR


def _fake_bpy(native):
    region = SimpleNamespace(type='WINDOW', width=800, height=600, y=0)
    area = SimpleNamespace(type='VIEW_3D', regions=[region], tag_redraw=MagicMock())
    window = SimpleNamespace(screen=SimpleNamespace(areas=[area]), workspace=SimpleNamespace(name="Layout"))
    wm = {}
    wm_obj = MagicMock()
    wm_obj.windows = [window]
    wm_obj.__setitem__ = lambda self, k, v: wm.__setitem__(k, v)
    mixar = SimpleNamespace(agent_halo_redraw=MagicMock()) if native else SimpleNamespace()
    bpy = SimpleNamespace(ops=SimpleNamespace(mixar=mixar),
                          data=SimpleNamespace(window_managers=[wm_obj]),
                          context=SimpleNamespace(workspace=None))
    return bpy, wm, area, mixar


@pytest.fixture
def halo():
    from mixar.modules.agent_viewport_lock.core import halo_renderer as H
    return H


def test_tick_mirrors_state_and_requests_a_cursor_redraw(monkeypatch, halo):
    bpy, wm, area, mixar = _fake_bpy(native=True)
    monkeypatch.setattr(halo, "bpy", bpy)
    halo.tag_view3d_redraw()
    assert wm == {halo.HALO_ACTIVE_WM_PROP: 1, halo.HALO_INSET_WM_PROP: 0}
    assert mixar.agent_halo_redraw.called and not area.tag_redraw.called
    halo.tag_view3d_redraw(active=False)
    assert wm[halo.HALO_ACTIVE_WM_PROP] == 0


def test_python_painter_stands_down_when_the_native_one_exists(monkeypatch, halo):
    bpy, *_ = _fake_bpy(native=True)
    monkeypatch.setattr(halo, "bpy", bpy)
    monkeypatch.setattr(halo, "is_agent_executing", lambda: True)
    monkeypatch.setattr(halo, "_draw_inner_glow", MagicMock(side_effect=AssertionError("drawn twice")))
    halo._draw_callback()


def test_older_binary_keeps_the_full_redraw_fallback(monkeypatch, halo):
    bpy, wm, area, _ = _fake_bpy(native=False)
    monkeypatch.setattr(halo, "bpy", bpy)
    halo.tag_view3d_redraw()
    assert area.tag_redraw.called and wm == {}

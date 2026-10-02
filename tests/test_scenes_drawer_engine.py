# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Scenes drawer in Engine workspaces.

The drawer used to poll for the "Zen Mode" workspace, so Engine had no panel,
no toggle, and Ctrl+` fell through to Blender. It now lives on the window's
main 3D View (the largest View3D) in every workspace:

- the native region poll picks the largest View3D of the screen, the first of
  equals, so a split layout shows one panel for the one WindowManager state;
- every operator resolves that host (context area, then its window, then any
  window), never a View3D whose drawer region failed its poll;
- Engine's overlapping Tool Settings strip clips the drawer's top;
- the stock header of the host viewport gets Zen's Scenes hamburger first, and
  the thumbnail snapshot / slide tick target the same host.

``bpy`` is a MagicMock in this suite: native code is executed from extracted
source against stub DNA types, Python through doubles.
"""
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from mixar.modules.space_mixie_chat.core import scene_tab_snapshot as SNAPSHOT
from mixar.modules.workflow.ui.headers import view3d_header_filter as HEADER

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/source/blender"
VIEW3D = SOURCE / "editors/space_view3d"
DRAWER = (VIEW3D / "view3d_scenes_drawer.cc").read_text()
DRAWER_HH = (VIEW3D / "view3d_scenes_drawer.hh").read_text()
ED_HEADER = (SOURCE / "editors/include/ED_scenes_drawer.hh").read_text()
AREA = (SOURCE / "editors/screen/area.cc").read_text()
RNA = (SOURCE / "makesrna/intern/rna_screen_mixar_scenes_drawer.hh").read_text()
QA = (VIEW3D / "view3d_scenes_drawer_qa.cc").read_text()
OPS = (VIEW3D / "view3d_scenes_drawer_ops.cc").read_text()


def _function(source: str, signature: str) -> str:
    """`signature` through the closing brace at column 0."""
    start = source.index(signature)
    return source[start:source.index("\n}\n", start) + 3]


# --- native host rule ---------------------------------------------------------

_STUBS = r'''
#include <cassert>
#include <vector>
#define SPACE_VIEW3D 1
#define SPACE_OUTLINER 3
#define RGN_TYPE_WINDOW 0
#define RGN_TYPE_NAV_BAR 13
#define RGN_FLAG_POLL_FAILED (1 << 10)
#define VIEW3D_SCENES_DRAWER_REGION_TYPE RGN_TYPE_NAV_BAR
template<typename T> struct ListBaseT {
  std::vector<T *> items;
  struct It {
    typename std::vector<T *>::const_iterator i;
    T &operator*() const { return **i; }
    It &operator++() { ++i; return *this; }
    bool operator!=(const It &other) const { return i != other.i; }
  };
  It begin() const { return {items.begin()}; }
  It end() const { return {items.end()}; }
};
struct vec2s { short x, y; };
struct ScrVert { vec2s vec; };
struct ARegion { int regiontype; int flag; };
struct ScrArea {
  int spacetype;
  ScrVert *v1, *v3;
  ListBaseT<ARegion> regionbase;
};
struct bScreen { ListBaseT<ScrArea> areabase; };
'''

_CASES = r'''
static ScrVert verts[16];
static int vert_count = 0;
static ScrArea area(int spacetype, short x0, short y0, short x1, short y1)
{
  ScrVert *a = &verts[vert_count++];
  ScrVert *b = &verts[vert_count++];
  a->vec = {x0, y0};
  b->vec = {x1, y1};
  return ScrArea{spacetype, a, b, {}};
}

int main()
{
  // Layout: outliner + properties are bigger editors, the 3D View still hosts.
  ScrArea outliner = area(SPACE_OUTLINER, 0, 0, 1900, 1000);
  ScrArea main_view = area(SPACE_VIEW3D, 0, 0, 1400, 900);
  bScreen layout{{{&outliner, &main_view}}};
  assert(drawer_area_is_main_view3d(&layout, &main_view));
  assert(!drawer_area_is_main_view3d(&layout, &outliner));

  // Animation: the small camera view never gets a second panel.
  ScrArea camera = area(SPACE_VIEW3D, 0, 500, 500, 900);
  ScrArea big = area(SPACE_VIEW3D, 500, 300, 1700, 900);
  bScreen animation{{{&camera, &big}}};
  assert(!drawer_area_is_main_view3d(&animation, &camera));
  assert(drawer_area_is_main_view3d(&animation, &big));

  // A user who grows the camera view moves the drawer with it.
  camera.v3->vec = {1600, 1000};
  assert(drawer_area_is_main_view3d(&animation, &camera));
  assert(!drawer_area_is_main_view3d(&animation, &big));

  // Equal halves: the first in screen order, exactly one host.
  ScrArea left = area(SPACE_VIEW3D, 0, 0, 800, 800);
  ScrArea right = area(SPACE_VIEW3D, 800, 0, 1600, 800);
  bScreen split{{{&left, &right}}};
  assert(drawer_area_is_main_view3d(&split, &left));
  assert(!drawer_area_is_main_view3d(&split, &right));

  // No 3D View, no screen, an area without vertices: no host.
  bScreen empty{{{&outliner}}};
  assert(!drawer_area_is_main_view3d(&empty, &outliner));
  assert(!drawer_area_is_main_view3d(nullptr, &main_view));
  ScrArea detached{SPACE_VIEW3D, nullptr, nullptr, {}};
  bScreen broken{{{&detached, &main_view}}};
  assert(drawer_area_is_main_view3d(&broken, &main_view));
  assert(!drawer_area_is_main_view3d(&broken, &detached));

  // Hosting is the drawer region's last poll; a failed one never hosts.
  ARegion window{RGN_TYPE_WINDOW, 0};
  ARegion drawer{VIEW3D_SCENES_DRAWER_REGION_TYPE, 0};
  main_view.regionbase.items = {&window, &drawer};
  assert(view3d_scenes_drawer_area_hosts(&main_view));
  drawer.flag = RGN_FLAG_POLL_FAILED;
  assert(!view3d_scenes_drawer_area_hosts(&main_view));
  outliner.regionbase.items = {&drawer};
  drawer.flag = 0;
  assert(!view3d_scenes_drawer_area_hosts(&outliner));
  assert(!view3d_scenes_drawer_area_hosts(nullptr));
  return 0;
}
'''


def test_native_host_rule_picks_the_window_main_view3d(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required for the native host rule")
    rule = _function(DRAWER, "static bool drawer_area_is_main_view3d(")
    hosts = _function(ED_HEADER, "inline bool view3d_scenes_drawer_area_hosts(")
    source = tmp_path / "host.cc"
    source.write_text(_STUBS + rule + hosts + _CASES)
    binary = tmp_path / "host"
    built = subprocess.run([compiler, "-std=c++17", str(source), "-o", str(binary)],
                           capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    executed = subprocess.run([str(binary)], capture_output=True, text=True)
    assert executed.returncode == 0, executed.stdout + executed.stderr


def test_region_poll_is_the_host_rule_in_every_workspace():
    poll = _function(DRAWER, "static bool drawer_region_poll(")
    assert "drawer_area_is_main_view3d(params->screen, params->area)" in poll
    first_layout = _function(DRAWER, "static bool drawer_area_hosts_in_wm(")
    assert "drawer_area_is_main_view3d(screen, area)" in first_layout
    for name, text in (("view3d_scenes_drawer.cc", DRAWER), ("view3d_scenes_drawer.hh", DRAWER_HH)):
        assert "Zen Mode" not in text, name
        assert "workspace_is_zen" not in text, name
    for path in VIEW3D.glob("view3d_scenes_drawer*"):
        assert "view3d_scenes_drawer_zen_active" not in path.read_text(), path.name


def test_operators_resolve_the_host_never_a_secondary_view3d():
    find = _function(DRAWER_HH, "inline ScrArea *view3d_scenes_drawer_area_find(")
    context_area = find.index("view3d_scenes_drawer_area_hosts(area)")
    context_window = find.index("CTX_wm_window(C)")
    any_window = find.index("wm->windows")
    assert context_area < context_window < any_window
    from_context = _function(DRAWER_HH, "inline ARegion *view3d_scenes_drawer_region_from_context(")
    assert "view3d_scenes_drawer_area_find(C)" in from_context
    assert "CTX_wm_area" not in from_context
    redraw = _function(OPS, "static void drawer_tag_redraw(")
    assert "view3d_scenes_drawer_area_find(C)" in redraw
    assert "CTX_wm_area" not in redraw


def test_a_view3d_that_lost_the_drawer_answers_no_hit_or_qa_target():
    rect = _function(ED_HEADER, "inline bool view3d_scenes_drawer_panel_rect_for(")
    assert "RGN_FLAG_POLL_FAILED" in rect
    provider = _function(QA, "void drawer_qa_targets(")
    assert provider.index("RGN_FLAG_POLL_FAILED") < provider.index("regiondata")


def test_engine_tool_settings_strip_clips_the_drawer_top():
    clip = _function(AREA, "static void mixar_scenes_drawer_headers_clip(")
    assert "ELEM(previous->regiontype, RGN_TYPE_HEADER, RGN_TYPE_TOOL_HEADER)" in clip
    # Zen keeps its floating-toolbar clip; its centred selection menu floats.
    assert "mixar_floating_headers_clip(region, rect)" in clip
    assert "BLI_rcti_size_y(&clipped) > 0" in clip
    site = AREA.split("Mixar: the Scenes drawer starts below the headers", 1)[1][:400]
    assert "mixar_scenes_drawer_headers_clip(area, region, &region->winrct)" in site
    assert "mixar_area_floats_viewport_chrome" not in site


def test_python_asks_native_which_area_hosts():
    assert '"mixar_scenes_drawer_hosts"' in RNA
    assert "view3d_scenes_drawer_area_hosts(area)" in RNA


# --- the Engine header --------------------------------------------------------

class _Layout:
    def __init__(self, calls):
        self.calls = calls

    def mixar_surface(self, **kwargs):
        self.calls.append(("surface", kwargs))
        return self

    def row(self, **_kwargs):
        return self


def _draw_header(monkeypatch, *, workspace, area):
    calls = []
    monkeypatch.setattr(HEADER.zen_scene_controls, "draw_scenes_button",
                        lambda surface, context: calls.append(("scenes", None)))
    monkeypatch.setattr(HEADER, "_original_header_draw",
                        lambda self, context: calls.append(("stock", None)))
    header = SimpleNamespace(layout=_Layout(calls))
    context = SimpleNamespace(workspace=SimpleNamespace(name=workspace), area=area)
    HEADER._patched_header_draw(header, context)
    return [name for name, _ in calls]


def test_engine_main_viewport_header_starts_with_the_scenes_toggle(monkeypatch):
    host = SimpleNamespace(mixar_scenes_drawer_hosts=lambda: True)
    for workspace in ("Layout", "Texturing", "Animation"):
        assert _draw_header(monkeypatch, workspace=workspace, area=host) == [
            "surface", "scenes", "stock"], workspace


def test_other_engine_viewports_keep_the_untouched_stock_header(monkeypatch):
    def broken():
        raise ReferenceError("area freed")

    for area in (SimpleNamespace(mixar_scenes_drawer_hosts=lambda: False),
                 SimpleNamespace(mixar_scenes_drawer_hosts=broken),
                 SimpleNamespace(), None):
        assert _draw_header(monkeypatch, workspace="Layout", area=area) == ["stock"]


# --- the slide tick and tab-switch snapshot target ------------------------------

def _area(kind, hosts=None):
    area = SimpleNamespace(type=kind, regions=[SimpleNamespace(type="HEADER"),
                                               SimpleNamespace(type="WINDOW")],
                           spaces=SimpleNamespace(active=f"{kind}-space"))
    if hosts is not None:
        area.mixar_scenes_drawer_hosts = lambda: hosts
    return area


def _windows(monkeypatch, *windows):
    wm = SimpleNamespace(windows=list(windows))
    monkeypatch.setattr(SNAPSHOT, "bpy", SimpleNamespace(context=SimpleNamespace(window_manager=wm)))


def _window(workspace, *areas, screen=True):
    return SimpleNamespace(workspace=SimpleNamespace(name=workspace),
                           screen=SimpleNamespace(areas=list(areas)) if screen else None)


def test_override_targets_the_engine_host_viewport(monkeypatch):
    camera = _area("VIEW_3D", hosts=False)
    main = _area("VIEW_3D", hosts=True)
    island = _window("Layout", screen=False)
    engine = _window("Animation", camera, _area("OUTLINER"), main)
    _windows(monkeypatch, island, engine)
    override = SNAPSHOT.drawer_view3d_override()
    assert override["area"] is main and override["window"] is engine
    assert override["region"].type == "WINDOW"
    assert override["space_data"] == "VIEW_3D-space"


def test_override_is_none_without_a_host(monkeypatch):
    _windows(monkeypatch, _window("Scripting", _area("VIEW_3D", hosts=False), _area("CONSOLE")))
    assert SNAPSHOT.drawer_view3d_override() is None


def test_override_falls_back_to_zen_on_a_build_without_the_rna(monkeypatch):
    zen_view = _area("VIEW_3D")
    _windows(monkeypatch, _window("Layout", _area("VIEW_3D")), _window("Zen Mode", zen_view))
    assert SNAPSHOT.drawer_view3d_override()["area"] is zen_view

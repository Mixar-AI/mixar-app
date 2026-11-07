# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Regression: finishing Director must survive a deleted local camera.

``_VIEW_STATES`` keeps Python ID references for the whole directing session.
Deleting the remembered datablock meanwhile (outliner delete, undo swapping
Main) frees the StructRNA underneath, and ``space.camera = dead_ref`` raised
``ReferenceError: StructRNA of type Object has been removed`` from
``restore_view`` — aborting the restore midway, so the chrome
(sidebar/toolbar) and view perspective were never brought back and Finish
left the user stranded in the calm shell.
"""

from contextlib import nullcontext
from types import SimpleNamespace

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core import viewport  # noqa: E402


class _DeadID:
    """Mimics a freed bpy ID: any attribute access raises ReferenceError."""

    @property
    def name(self):
        raise ReferenceError("StructRNA of type Object has been removed")


class _Region3D:
    def __init__(self):
        self.view_perspective = 'CAMERA'
        self.view_location = None
        self.view_rotation = None
        self.view_distance = 0.0


class _Space:
    def __init__(self):
        self.lock_camera = True
        self.camera = _DeadID()
        self.show_region_ui = False
        self.show_region_toolbar = False
        self.region_3d = _Region3D()


class _Area:
    def tag_redraw(self):
        pass


def _seed_state(scene, *, camera, camera_name):
    viewport._VIEW_STATES[viewport._scene_key(scene)] = {
        "view_perspective": 'PERSP',
        "view_location": (1.0, 2.0, 3.0),
        "view_rotation": (1.0, 0.0, 0.0, 0.0),
        "view_distance": 12.0,
        "lock_camera": False,
        "local_camera": camera,
        "local_camera_name": camera_name,
        "chrome": {"show_region_ui": True, "show_region_toolbar": True},
    }


def test_live_id_filters_freed_references():
    live = type("Live", (), {"name": "Camera"})()

    assert viewport._live_id(None) is None
    assert viewport._live_id(live) is live
    assert viewport._live_id(_DeadID()) is None


def test_restore_view_survives_a_deleted_local_camera(monkeypatch):
    scene = object()
    space = _Space()
    monkeypatch.setattr(
        viewport,
        "find_view3d_context",
        lambda _context: (None, _Area(), None, space),
    )
    monkeypatch.setattr(viewport.bpy.data.objects, "get", lambda _name: None)
    _seed_state(scene, camera=_DeadID(), camera_name="Ghost Camera")

    viewport.restore_view(SimpleNamespace(temp_override=lambda **kw: nullcontext()), scene)

    # The dead reference resolved to None instead of raising, and the WHOLE
    # restore ran: chrome and view state are back, the camera slot cleared.
    assert space.camera is None
    assert space.show_region_ui is True
    assert space.show_region_toolbar is True
    assert space.lock_camera is False
    assert space.region_3d.view_perspective == 'PERSP'
    assert space.region_3d.view_location == (1.0, 2.0, 3.0)
    assert space.region_3d.view_distance == 12.0


def test_restore_view_recovers_local_camera_by_name(monkeypatch):
    """Undo can free-and-recreate the object; the stored name recovers it."""
    scene = object()
    space = _Space()
    recovered = type("Recovered", (), {"name": "Ghost Camera"})()
    monkeypatch.setattr(
        viewport,
        "find_view3d_context",
        lambda _context: (None, _Area(), None, space),
    )
    monkeypatch.setattr(
        viewport.bpy.data.objects,
        "get",
        lambda name: recovered if name == "Ghost Camera" else None,
    )
    _seed_state(scene, camera=_DeadID(), camera_name="Ghost Camera")

    viewport.restore_view(SimpleNamespace(temp_override=lambda **kw: nullcontext()), scene)

    assert space.camera is recovered


class _RemovedArea:
    @property
    def type(self):
        raise ReferenceError("ScrArea has been removed")


def _context(area, areas):
    window = SimpleNamespace(screen=SimpleNamespace(areas=areas))
    return SimpleNamespace(
        area=area, window=window,
        window_manager=SimpleNamespace(windows=[window]),
        temp_override=lambda **kw: nullcontext(),
    )


def test_restore_removed_area_without_live_target_clears_saved_state():
    scene = object()
    _seed_state(scene, camera=None, camera_name="")
    viewport.restore_view(_context(_RemovedArea(), []), scene)
    assert viewport._scene_key(scene) not in viewport._VIEW_STATES


def test_restore_uses_replacement_area_and_live_override():
    scene = object()
    space = _Space()
    space.show_region_hud = False
    space.overlay = SimpleNamespace(show_text=False)
    region = SimpleNamespace(type='WINDOW')
    area = SimpleNamespace(
        type='VIEW_3D', regions=[region], spaces=SimpleNamespace(active=space),
        width=800, height=600, tag_redraw=lambda: None,
    )
    context = _context(_RemovedArea(), [area])
    overrides = []
    def override(**kw):
        overrides.append(kw)
        return nullcontext()
    context.temp_override = override
    _seed_state(scene, camera=None, camera_name="")
    saved = viewport._VIEW_STATES[viewport._scene_key(scene)]
    saved['chrome']['show_region_hud'] = True
    saved['overlay'] = {'show_text': True}

    viewport.restore_view(context, scene)

    assert space.show_region_hud and space.show_region_toolbar and space.show_region_ui
    assert space.overlay.show_text
    assert space.region_3d.view_perspective == 'PERSP'
    assert overrides == [dict(window=context.window, area=area, region=region)]
    assert viewport._scene_key(scene) not in viewport._VIEW_STATES


def test_readable_but_detached_area_is_not_used():
    stale = SimpleNamespace(type='VIEW_3D')  # No regions/spaces may be read.
    assert viewport.find_view3d_context(_context(stale, [])) is None

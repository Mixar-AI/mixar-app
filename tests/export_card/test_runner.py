# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Export button's flow: destination problems and existing files stop
it before any work; a model export is deferred one tick and lands on DONE
with the lane's facts; a render starts in the background with the user's
file as its destination."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.modules.export_card import constants as C
from mixar.modules.export_card.core import runner, state


def _card(tmp_path, target=C.GLTF, **extra):
    values = dict(target=target, state=C.IDLE, file_name="nook", folder=str(tmp_path),
                  engine='web', scope='SCENE', animation='ALL', gltf_file='GLB', usd_file='USDZ',
                  cameras_lights=True, texture_format='AUTO', draco=False, apply_modifiers=True,
                  y_up=True, render_format='PNG', renderer='EEVEE', quality='GOOD', width=640,
                  height=480, camera='Camera', transparent=False, frame_start=1, frame_end=24,
                  fps=24, project_strip_chat=False, project_compress=True)
    values.update(extra)
    return SimpleNamespace(**values)


@pytest.fixture
def immediate(monkeypatch):
    """Run the deferred export now, outside any window, on our own bpy
    (another suite may leave the shared stub without `context`)."""
    fake = MagicMock()
    fake.app.timers.register = lambda fn, first_interval=0: fn()
    fake.path.abspath = lambda path: path
    monkeypatch.setattr(runner, "bpy", fake)
    monkeypatch.setattr(runner, "_redraw", lambda: None)
    state.clear_result()
    return fake


def test_missing_folder_is_an_error_before_any_work(tmp_path, immediate):
    p = _card(tmp_path, folder="")
    runner.begin(SimpleNamespace(window=None), p)
    assert p.state == C.ERROR
    assert state.result()["error"] == "Choose a folder to export to."


def test_existing_file_asks_before_replacing(tmp_path, immediate):
    (tmp_path / "nook.glb").write_bytes(b"old")
    p = _card(tmp_path)
    runner.begin(SimpleNamespace(window=None), p)
    assert p.state == 'CONFIRM'
    assert state.result()["name"] == "nook.glb"


def test_model_export_lands_on_done_with_lane_facts(tmp_path, immediate, monkeypatch):
    from mixar.modules.space_mixie_chat.core import agent_export
    seen = {}

    def fake_export(path, spec, *, via, tool, overrides):
        seen.update(path=path, spec=spec, via=via, overrides=overrides)
        return {"success": True, "file_size_bytes": 2048, "mesh_count": 3, "warning": "",
                "verification": {"checked": True, "passed": True}}

    monkeypatch.setattr(agent_export, "export_to_path", fake_export)
    p = _card(tmp_path)
    immediate.context.window_manager.mixar_export_card = p
    runner.begin(SimpleNamespace(window=None), p, replace=True)
    assert p.state == C.DONE
    assert seen["path"].endswith("nook.glb") and seen["via"] == "export_card"
    assert seen["overrides"]["export_cameras"] is True
    facts = state.result()
    assert (facts["kind"], facts["size"], facts["passed"]) == ("file", 2048, True)


def test_lane_failure_is_an_error_with_detail(tmp_path, immediate, monkeypatch):
    from mixar.modules.space_mixie_chat.core import agent_export
    monkeypatch.setattr(agent_export, "export_to_path",
                        lambda *a, **k: {"success": False, "error": "No mesh objects"})
    p = _card(tmp_path)
    immediate.context.window_manager.mixar_export_card = p
    runner.begin(SimpleNamespace(window=None), p)
    assert p.state == C.ERROR
    assert state.result()["detail"] == "No mesh objects"


@pytest.mark.parametrize("target, ext, kind", [(C.IMAGE, ".png", 'image'),
                                               (C.VIDEO, ".mp4", 'video')])
def test_render_starts_in_the_background_to_the_users_file(tmp_path, immediate, monkeypatch,
                                                           target, ext, kind):
    from mixar.modules.scene_render.core import jobs
    calls = []

    def fake_start(context, key, kind, label='', destination='', **options):
        calls.append(dict(kind=kind, destination=destination, options=options))
        return {"status": "started", "job_id": key}

    monkeypatch.setattr(jobs, "start", fake_start)
    p = _card(tmp_path, target=target)
    runner.begin(SimpleNamespace(window=object()), p)
    assert p.state == C.DONE and state.result()["kind"] == "render"
    assert calls[0]["kind"] == kind
    assert calls[0]["destination"].endswith("nook" + ext)
    assert calls[0]["options"]["camera"] == "Camera"


def test_render_busy_is_explained(tmp_path, immediate, monkeypatch):
    from mixar.modules.scene_render.core import jobs
    monkeypatch.setattr(jobs, "start", lambda *a, **k: {"status": "busy",
                                                        "error": "another_render_running"})
    p = _card(tmp_path, target=C.IMAGE)
    runner.begin(SimpleNamespace(window=object()), p)
    assert p.state == C.ERROR
    assert "Another render is running" in state.result()["error"]

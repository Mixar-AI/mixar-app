# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""`agent_export.export_to_path(overrides=…)`: the Export card's pinned
exporter kwargs reach the exporter, the lane's own staging still wins over
them, and nothing in the spec can pin kwargs."""

from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.modules.space_mixie_chat.core import agent_export


class FakeMesh:
    """Hashable like a Blender object (the lane keeps targets in a set)."""
    name, type, parent, modifiers, mode = "Cube", 'MESH', None, [], 'OBJECT'
    data = SimpleNamespace(materials=[])

    def select_set(self, value):
        pass


@pytest.fixture
def lane(monkeypatch):
    mesh = FakeMesh()
    seen = {}

    @contextmanager
    def clips(*_a):
        yield [], []

    def run(fmt, path, use_case, animations, overrides, profile):
        seen["overrides"] = dict(overrides or {})
        return {'FINISHED'}, dict(overrides or {}), "all", ""

    # Our own bpy: another suite may leave the shared stub without `context`.
    monkeypatch.setattr(agent_export, "bpy", MagicMock())
    monkeypatch.setattr(agent_export, "export_targets", lambda spec: [mesh])
    monkeypatch.setattr(agent_export, "preflight_meshes", lambda spec, meshes: {"ready": True})
    monkeypatch.setattr(agent_export, "clip_selection", clips)
    monkeypatch.setattr(agent_export, "_temporary_export_materials", lambda meshes: nullcontext())
    monkeypatch.setattr(agent_export, "writes_gltf_skin", lambda mesh: False)
    monkeypatch.setattr(agent_export, "verify_export",
                        lambda *a: {"checked": True, "passed": True})
    monkeypatch.setattr(agent_export, "_run_operator", run)
    return seen


def test_pinned_overrides_reach_the_exporter(lane, tmp_path):
    result = agent_export.export_to_path(
        str(tmp_path / "a.fbx"), {"format": "fbx", "overrides": {"evil": 1},
                                  "exporter_overrides": {"evil": 2}},
        via="export_card", tool="export_card", overrides={"embed_textures": False})
    assert result["success"] is True
    assert lane["overrides"] == {"embed_textures": False}


def test_without_overrides_the_spec_pins_nothing(lane, tmp_path):
    agent_export.export_to_path(str(tmp_path / "a.fbx"),
                                {"format": "fbx", "overrides": {"evil": 1}})
    assert lane["overrides"] == {}


def test_lane_stl_scale_wins_over_pinned_kwargs(lane, tmp_path):
    agent_export.export_to_path(str(tmp_path / "a.stl"),
                                {"format": "stl", "stl": {"scale": 1000.0}},
                                overrides={"global_scale": 5.0, "apply_modifiers": False})
    assert lane["overrides"]["global_scale"] == 1000.0
    assert lane["overrides"]["apply_modifiers"] is False


def test_usdc_is_a_lane_format(lane, tmp_path):
    result = agent_export.export_to_path(str(tmp_path / "a.usdc"), {"format": "usdc"})
    assert result["success"] is True

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-Python tests for agent_tools._common._resolve_mesh_objects."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
COMMON_PY = ROOT / "src/scripts/mixar/modules/paint/core/agent_tools/_common.py"


def _mesh(name):
    return types.SimpleNamespace(name=name, type="MESH", children_recursive=[])


class _FakeObjects:
    """Mimics bpy.data.objects: iterable plus .get(name)."""

    def __init__(self, objs):
        self._objs = list(objs)
        self._by_name = {o.name: o for o in objs}

    def __iter__(self):
        return iter(self._objs)

    def get(self, name):
        return self._by_name.get(name)


def _load_common(monkeypatch, *, selected=None, active=None, scene_objs=None, data_objs=None):
    fake_bpy = types.SimpleNamespace(
        context=types.SimpleNamespace(
            selected_objects=list(selected or []),
            active_object=active,
            scene=types.SimpleNamespace(objects=list(scene_objs or [])),
        ),
        data=types.SimpleNamespace(objects=_FakeObjects(data_objs or [])),
    )
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)

    for name in (
        "mixar",
        "mixar.config",
        "mixar.modules",
        "mixar.modules.paint",
        "mixar.modules.paint.utils",
    ):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    log_mod = types.ModuleType("mixar.config.logging_config")
    log_mod.get_logger = lambda *a, **k: MagicMock()
    monkeypatch.setitem(sys.modules, "mixar.config.logging_config", log_mod)
    const_mod = types.ModuleType("mixar.modules.paint.utils.constants")
    const_mod.MP_GROUP_PREFIX = "MP_"
    monkeypatch.setitem(sys.modules, "mixar.modules.paint.utils.constants", const_mod)

    spec = importlib.util.spec_from_file_location("agent_tools_common_under_test", COMMON_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_resolve_targets_empty_context_resolves_nothing(monkeypatch):
    """No selection + no active object resolves NO targets — the tool call
    must fail (callers report "No mesh objects found") instead of silently
    targeting every mesh in the scene."""
    in_scene = [_mesh("A"), _mesh("B")]
    other_scene_only = _mesh("C")
    common = _load_common(
        monkeypatch,
        selected=[],
        active=None,
        scene_objs=in_scene,
        data_objs=in_scene + [other_scene_only],
    )
    targets, missing = common._resolve_mesh_objects()
    assert targets == []
    assert missing == []


def test_resolve_targets_named_uses_data_lookup(monkeypatch):
    """Explicit names still resolve through bpy.data.objects.get, with misses reported."""
    a = _mesh("A")
    c = _mesh("C")
    common = _load_common(
        monkeypatch,
        scene_objs=[a],
        data_objs=[a, c],
    )
    targets, missing = common._resolve_mesh_objects(["C", "Z"])
    assert sorted(o.name for o in targets) == ["C"]
    assert missing == ["Z"]


def test_resolve_targets_prefers_selection_over_scene(monkeypatch):
    """A live selection wins over the scene-wide fallback."""
    a, b = _mesh("A"), _mesh("B")
    common = _load_common(
        monkeypatch,
        selected=[a],
        scene_objs=[a, b],
        data_objs=[a, b],
    )
    targets, _ = common._resolve_mesh_objects()
    assert sorted(o.name for o in targets) == ["A"]

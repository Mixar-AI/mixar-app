# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Build/Combat panels' shared check (``game_panels.checked_scene``):
reused within its TTL only while nothing it reads changed. A role tag or a
pose-marker edit (an agent script, Auto-assign) re-inspects at once, so a
panel never shows "no player" next to a Roles count of one.

The panel module subclasses ``bpy.types.Panel`` and cannot be imported with
bpy mocked, so the cache's own definitions are lifted from its source (the
``ast`` pattern of the other UI pins) and run against fakes."""

import ast
import types
from pathlib import Path

import pytest

from mixar.modules.game_studio import constants
from mixar.modules.game_studio.constants import PARAMS_PROP, ROLE_PROP

PANELS = Path(__file__).parents[2] / "src/scripts/mixar/modules/game_studio/ui/panels/game_panels.py"
CACHE_NAMES = {"CHECK_TTL_S", "_checked", "_edit_signature", "checked_scene"}


def _load_cache(namespace):
    tree = ast.parse(PANELS.read_text(encoding="utf-8"))
    body = [node for node in tree.body
            if (isinstance(node, ast.FunctionDef) and node.name in CACHE_NAMES)
            or (isinstance(node, ast.Assign) and {getattr(t, "id", "") for t in node.targets} & CACHE_NAMES)]
    assert {getattr(n, "name", None) or n.targets[0].id for n in body} == CACHE_NAMES
    exec(compile(ast.Module(body=body, type_ignores=[]), str(PANELS), "exec"), namespace)
    return types.SimpleNamespace(**{name: namespace[name] for name in CACHE_NAMES}, ns=namespace)


@pytest.fixture
def panels(monkeypatch, make_obj, make_scene):
    from mixar.modules.game_studio.core import exporter
    calls = []
    monkeypatch.setattr(exporter, "inspect", lambda scene: calls.append(1) or {"n": len(calls)})
    action = types.SimpleNamespace(name="boss_attack_slam", pose_markers=[])
    clock = types.SimpleNamespace(now=100.0)
    game_panels = _load_cache({
        "bpy": types.SimpleNamespace(data=types.SimpleNamespace(actions=[action])),
        "time": types.SimpleNamespace(monotonic=lambda: clock.now),
        **{name: getattr(constants, name) for name in ("ROLE_PROP", "PARAMS_PROP", "PART_ONLY_PROP")}})
    scene = make_scene([make_obj("boss_character_Root", "EMPTY"), make_obj("Player_Root", "EMPTY")])
    return game_panels, scene, action, calls, clock


def test_reused_within_the_ttl_while_nothing_changed(panels):
    game_panels, scene, _action, calls, _clock = panels
    first = game_panels.checked_scene(scene)
    assert game_panels.checked_scene(scene) is first and len(calls) == 1


def test_a_role_or_param_change_reinspects_within_the_ttl(panels):
    game_panels, scene, _action, _calls, _clock = panels
    game_panels.checked_scene(scene)
    scene.objects.get("Player_Root")[ROLE_PROP] = "player"
    assert game_panels.checked_scene(scene)["n"] == 2
    scene.objects.get("Player_Root")[PARAMS_PROP] = '{"hp": 150}'
    assert game_panels.checked_scene(scene)["n"] == 3
    del scene.objects.get("Player_Root")[ROLE_PROP]
    assert game_panels.checked_scene(scene)["n"] == 4


def test_a_pose_marker_change_reinspects_within_the_ttl(panels):
    game_panels, scene, action, _calls, _clock = panels
    game_panels.checked_scene(scene)
    action.pose_markers = [types.SimpleNamespace(name="hit_start", frame=28)]
    assert game_panels.checked_scene(scene)["n"] == 2
    action.pose_markers[0].frame = 29
    assert game_panels.checked_scene(scene)["n"] == 3
    assert game_panels.checked_scene(scene)["n"] == 3  # and reused again after


def test_a_spec_change_reinspects_and_the_ttl_still_expires(panels):
    game_panels, scene, _action, _calls, clock = panels
    game_panels.checked_scene(scene)
    scene["mixar_game_spec"] = '{"template": "boss_fight"}'
    assert game_panels.checked_scene(scene)["n"] == 2
    clock.now += game_panels.CHECK_TTL_S + 0.01
    assert game_panels.checked_scene(scene)["n"] == 3

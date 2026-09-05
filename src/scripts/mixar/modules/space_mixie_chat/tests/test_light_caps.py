# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Final-render lighting cap (#1270) — pathological energies only.

QA (Ajay, Aug 17): "Lighting intensity to be in check while rendering, if it
is beyond threshold reduce the intensity." LLM-authored bpy scripts
sometimes write 1e6 W point lights or 500 W/m^2 suns that blow the
deliverable render out. The cap:

- applies generous thresholds (configurable backend-side, passed as
  ``light_caps``) — legitimate bright scenes pass untouched
- is RENDER-ONLY: originals saved, restored with the rest of the settings
- covers lights (per-type), emission shader strengths, world background
- mirrors between the addon operator and the backend sync template
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.ui.operators import (  # noqa: E402
    agent_final_render_ops as ops,
)


class _Light:
    def __init__(self, name, type_, energy):
        self.name = name
        self.type = type_
        self.energy = energy


class _Socket:
    def __init__(self, value):
        self.default_value = value


class _EmissionNode:
    def __init__(self, strength):
        self.type = "EMISSION"
        self.name = "Emission"
        self.inputs = {"Strength": _Socket(strength)}


class _NamedList(list):
    """A bpy collection stand-in: iterable + .get(name)."""

    def get(self, name):
        return next((x for x in self if x.name == name), None)


class _Nodes(dict):
    """A bpy node collection stand-in: .get(name) + iterating the NODES."""

    def get(self, name):
        return dict.get(self, name)

    def __iter__(self):
        return iter(self.values())


class _NodeTree:
    def __init__(self, nodes):
        # Accept a dict {name: node} OR a list of nodes (keyed by .name).
        if isinstance(nodes, dict):
            self.nodes = _Nodes(nodes)
        else:
            self.nodes = _Nodes({n.name: n for n in nodes})


class _Material:
    def __init__(self, name, nodes):
        self.name = name
        self.use_nodes = True
        self.node_tree = _NodeTree(nodes)


def _bpy(lights=(), materials=(), world_strength=None):
    world = None
    if world_strength is not None:
        world = MagicMock()
        world.use_nodes = True
        world.node_tree = _NodeTree({
            "Background": _BackgroundNode(world_strength),
        })
    m = MagicMock()
    m.data.lights = _NamedList(lights)
    m.data.materials = _NamedList(materials)
    m.context.scene.world = world
    return m


class _BackgroundNode:
    def __init__(self, strength):
        self.type = "BACKGROUND"
        self.name = "Background"
        self.inputs = {"Strength": _Socket(strength)}


@pytest.fixture
def bpy_env(monkeypatch):
    holder = MagicMock()

    def install(lights=(), materials=(), world_strength=None):
        m = _bpy(lights, materials, world_strength)
        holder.data = m.data
        holder.context = m.context
        return m

    monkeypatch.setattr(ops, "bpy", holder)
    install.holder = holder
    return install


def _scene_of(installed):
    return installed.context.scene


def test_pathological_energies_are_capped(bpy_env):
    installed = bpy_env(lights=[
        _Light("Sun", "SUN", 500.0),        # > 50 sun cap
        _Light("Lamp", "POINT", 1_000_000.0),  # > 10000 W
        _Light("Fine", "AREA", 800.0),      # fine
    ])
    scene = _scene_of(installed)
    originals, capped = ops._cap_lights(
        scene,
        {"sun_energy": 50.0, "light_energy": 10000.0},
    )
    assert capped == ["Sun", "Lamp"]
    assert installed.data.lights[0].energy == 50.0
    assert installed.data.lights[1].energy == 10000.0
    assert installed.data.lights[2].energy == 800.0  # untouched
    assert originals["light:Sun"] == 500.0
    assert originals["light:Lamp"] == 1_000_000.0


def test_emission_and_world_capped(bpy_env):
    installed = bpy_env(
        materials=[_Material("Glow", [_EmissionNode(5000.0)])],
        world_strength=500.0,
    )
    originals, capped = ops._cap_lights(
        _scene_of(installed),
        {"emission_strength": 1000.0, "world_strength": 50.0},
    )
    assert capped == ["Glow (emission)", "world background"]
    assert originals["emission:Glow:Emission"] == 5000.0
    assert originals["world:Background"] == 500.0


def test_restore_returns_original_energies(bpy_env):
    installed = bpy_env(lights=[_Light("Sun", "SUN", 500.0)])
    scene = _scene_of(installed)
    originals, _ = ops._cap_lights(scene, {"sun_energy": 50.0})
    assert installed.data.lights[0].energy == 50.0

    ops._restore_lights(scene, originals)
    assert installed.data.lights[0].energy == 500.0


def test_legitimate_bright_scene_untouched(bpy_env):
    installed = bpy_env(lights=[
        _Light("Sun", "SUN", 5.0),
        _Light("Key", "AREA", 800.0),
        _Light("Rim", "SPOT", 3000.0),
    ])
    _, capped = ops._cap_lights(
        _scene_of(installed),
        {"sun_energy": 50.0, "light_energy": 10000.0},
    )
    assert capped == []


def test_default_caps_when_backend_sends_none(bpy_env):
    """Old backend (no light_caps param) still gets the sane defaults."""
    installed = bpy_env(lights=[_Light("Lamp", "POINT", 5_000_000.0)])
    _, capped = ops._cap_lights(_scene_of(installed), {})
    assert capped == ["Lamp"]
    assert installed.data.lights[0].energy == 10000.0


def test_parse_light_caps_tolerates_garbage():
    assert ops._parse_light_caps('{"sun_energy": 25}') == {"sun_energy": 25}
    assert ops._parse_light_caps("not json") == {}
    assert ops._parse_light_caps("") == {}
    assert ops._parse_light_caps('["array"]') == {}

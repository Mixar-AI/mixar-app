# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Engine binding and world preservation are independent of header redraws."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.modules.workflow.core import zen_scene


@pytest.mark.parametrize("engine,owner,prop", [
    ("CYCLES", "cycles", "samples"),
    ("BLENDER_EEVEE", "eevee", "taa_render_samples"),
    ("BLENDER_WORKBENCH", "display", "render_aa"),
])
def test_samples_bind_to_final_render_settings(engine, owner, prop):
    scene = SimpleNamespace(render=SimpleNamespace(engine=engine),
                            cycles=object(), eevee=object(), display=object())
    assert zen_scene.render_samples_binding(scene) == (getattr(scene, owner), prop)


def test_unknown_engine_and_missing_cycles_have_no_misleading_sample_field():
    for engine in ("CUSTOM_ENGINE", "CYCLES"):
        assert zen_scene.render_samples_binding(
            SimpleNamespace(render=SimpleNamespace(engine=engine))) is None


@pytest.mark.parametrize("engine,owner,prop", [
    ("CYCLES", "cycles", "preview_samples"),
    ("BLENDER_EEVEE", "eevee", "taa_samples"),
    ("BLENDER_WORKBENCH", "display", "viewport_aa"),
])
def test_viewport_samples_are_independent_of_final_render(engine, owner, prop):
    settings = SimpleNamespace(samples=128, preview_samples=16,
                               taa_render_samples=64, taa_samples=8,
                               render_aa="32", viewport_aa="8")
    scene = SimpleNamespace(render=SimpleNamespace(engine=engine),
                            **{owner: settings})
    render_owner, render_prop = zen_scene.render_samples_binding(scene)
    saved = getattr(render_owner, render_prop)
    viewport_owner, viewport_prop = zen_scene.render_samples_binding(scene, "VIEWPORT")
    assert (viewport_owner, viewport_prop) == (settings, prop)
    setattr(viewport_owner, viewport_prop, "16" if engine == "BLENDER_WORKBENCH" else 24)
    assert getattr(render_owner, render_prop) == saved


@pytest.mark.parametrize("original", [None, object()])
def test_sky_toggle_restores_world_and_reuses_its_own_world(original):
    sky = object()
    state = SimpleNamespace(sky_world=sky, previous_world=None)
    scene = SimpleNamespace(world=original, mixar_zen_sky=state)
    zen_scene.set_sky_enabled(scene, True)
    zen_scene.set_sky_enabled(scene, True)  # Never overwrite the saved world.
    assert zen_scene.sky_enabled(scene)
    assert scene.world is sky
    zen_scene.set_sky_enabled(scene, False)
    assert scene.world is original
    zen_scene.set_sky_enabled(scene, True)
    assert scene.world is sky
    assert state.previous_world is original


def test_external_world_change_is_authoritative():
    sky, external = object(), object()
    state = SimpleNamespace(sky_world=sky, previous_world=object())
    scene = SimpleNamespace(world=external, mixar_zen_sky=state)
    assert not zen_scene.sky_enabled(scene)
    zen_scene.set_sky_enabled(scene, False)
    assert scene.world is external
    zen_scene.set_sky_enabled(scene, True)
    zen_scene.set_sky_enabled(scene, False)
    assert scene.world is external


def test_failed_sky_creation_leaves_original_world_and_no_orphan(monkeypatch):
    original = object()
    state = SimpleNamespace(sky_world=None, previous_world=None)
    scene = SimpleNamespace(world=original, mixar_zen_sky=state)
    worlds = MagicMock()
    worlds.new.return_value.node_tree.nodes.new.side_effect = RuntimeError("Unavailable")
    monkeypatch.setattr(zen_scene, "bpy", SimpleNamespace(data=SimpleNamespace(worlds=worlds)))
    with pytest.raises(RuntimeError, match="Unavailable"):
        zen_scene.set_sky_enabled(scene, True)
    assert scene.world is original
    assert state.sky_world is None
    assert state.previous_world is None
    worlds.remove.assert_called_once_with(worlds.new.return_value)

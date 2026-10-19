# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contract v1.4 (arena feel), client parts: optional strafe/walk-back
player states, the ``world`` atmosphere fields, and the scene's own lights
in the game GLB (area lights stood in by spots for the export only)."""

import types
from pathlib import Path

import pytest

from mixar.modules.game_studio.constants import BOSS_WORLD_DEFAULTS, ROLE_PROP
from mixar.modules.game_studio.core import characters, spec, world

CHAT_CORE = Path(__file__).parents[2] / "src/scripts/mixar/modules/space_mixie_chat/core"


# --- §1 optional states ------------------------------------------------------------

@pytest.mark.parametrize("clip,state", [("player_strafe_left", "strafe_left"), ("player_strafe_right", "strafe_right"),
                                        ("player_walk_back", "walk_back"), ("player_strafe", None)])
def test_optional_player_states_classify(clip, state):
    assert characters.classify(clip, "player_", "player") == state
    assert characters.classify(clip.replace("player_", "boss_"), "boss_", "boss") is None  # player only


def _rig_with(names, make_obj):
    root = make_obj("Player_Root", "EMPTY")
    rig = make_obj("Player_Rig", "ARMATURE", parent=root)
    mesh = make_obj("Player_Skinned", "MESH", parent=rig)
    mesh.modifiers = [types.SimpleNamespace(type="ARMATURE", object=rig)]
    actions = [types.SimpleNamespace(name=n, frame_range=(1, 25), pose_markers=[]) for n in names]
    rig.animation_data = types.SimpleNamespace(action=None, nla_tracks=[
        types.SimpleNamespace(strips=[types.SimpleNamespace(name=a.name, action=a)]) for a in actions])
    return root, [root, rig, mesh]


def test_optional_states_export_and_are_never_missing(make_obj):
    root, subtree = _rig_with(["player_idle", "player_run", "player_strafe_left"], make_obj)
    found = characters.describe(root, "player", {}, subtree)
    assert found["clips"]["strafe_left"] == ["player_strafe_left"]
    assert "strafe_left" not in found["missing"] and "strafe_right" not in found["missing"]
    assert found["optional_missing"] == ["strafe_right", "walk_back"]
    assert "player_strafe_left" in characters.export_clips([found])
    errors, warnings = spec.validate_spec(spec.build_spec(
        spec.merge_settings(spec.DEFAULT_SETTINGS, {"template": "boss_fight"})[0],
        [{"name": "Player_Root", "role": "player", "params": {}}, {"name": "B", "role": "boss", "params": {}}]),
        [characters.public(found)])
    assert not any("strafe" in line or "walk_back" in line for line in errors + warnings)


# --- §3 world fields -----------------------------------------------------------------

def test_boss_fight_fills_the_atmosphere_defaults_on_load(make_scene):
    scene = make_scene()
    merged, _ = spec.merge_settings(spec.DEFAULT_SETTINGS, {"template": "boss_fight"})
    spec.save_settings(scene, merged)
    loaded = spec.load_settings(scene)["world"]
    assert {k: loaded[k] for k in BOSS_WORLD_DEFAULTS} == BOSS_WORLD_DEFAULTS
    assert "fog" not in spec.load_settings(make_scene())["world"]  # other templates: absent


def test_world_fields_validate_and_merge():
    base, _ = spec.merge_settings(spec.DEFAULT_SETTINGS, {"template": "boss_fight"})
    base["world"] = world.fill_boss_defaults(base["world"])
    merged, errors = spec.merge_settings(base, {"world": {"fog": {"density": 0.03}, "preset": "cavern",
                                                          "bloom": False, "scene_lights": False}})
    assert errors == [] and merged["world"]["fog"] == {"density": 0.03, "height": 2.0, "color": [0.55, 0.45, 0.4]}
    assert merged["world"]["preset"] == "cavern" and merged["world"]["bloom"] is False
    off, _ = spec.merge_settings(merged, {"world": {"fog": False}})
    assert off["world"]["fog"] is False
    on, _ = spec.merge_settings(off, {"world": {"fog": True}})
    assert on["world"]["fog"]["density"] == 0.012
    bad, errors = spec.merge_settings(merged, {"world": {"fog": {"density": 2, "color": [1, 1]}, "preset": "noon",
                                                         "bloom": "yes"}})
    assert len(errors) == 3 and bad["world"]["fog"]["density"] == 0.03 and bad["world"]["preset"] == "cavern"
    assert spec.merge_settings(merged, {"world": {"fog": {"mist": 1}}})[1] == ["unknown setting world.fog.mist"]


def test_leaving_boss_fight_drops_untouched_atmosphere_defaults():
    base, _ = spec.merge_settings(spec.DEFAULT_SETTINGS, {"template": "boss_fight"})
    world.fill_boss_defaults(base["world"])
    base["world"]["preset"] = "night"  # the user's own choice survives
    left, _ = spec.merge_settings(base, {"template": "third_person"})
    assert "scene_lights" not in left["world"] and "fog" not in left["world"] and "bloom" not in left["world"]
    assert left["world"]["preset"] == "night"
    kept, _ = spec.merge_settings(base, {"template": "top_down", "world": {"scene_lights": True}})
    assert kept["world"]["scene_lights"] is True


# --- §3 scene lights ------------------------------------------------------------------

def test_scene_lights_skip_hidden_and_ignored(make_obj, make_scene):
    from mixar.modules.game_studio.core import exporter
    preview = make_obj("boss_playback_preview_Root", "EMPTY")
    preview[ROLE_PROP] = "ignore"
    arena = make_obj("arena_lighting_Root", "EMPTY")
    lights = [make_obj("Key", "LIGHT", parent=arena), make_obj("Rim", "LIGHT", parent=preview),
              make_obj("Off", "LIGHT", visible=False), make_obj("Light", "LIGHT")]
    scene = make_scene([preview, arena] + lights)
    assert [o.name for o in exporter.scene_lights(scene)] == ["Key", "Light"]
    lane = exporter.export_spec([], None, exporter.scene_lights(scene))
    assert lane["scene_lights"] is True and lane["extra_object_names"] == ["Key", "Light"]
    assert "scene_lights" not in exporter.export_spec([])


class _Lights(list):
    def new(self, name, kind):
        data = types.SimpleNamespace(name=name, type=kind)
        self.append(data)
        return data


def test_area_lights_stand_in_as_spots_for_the_export_only(monkeypatch):
    from mixar.modules.space_mixie_chat.core import export_lights
    removed = []
    lights, objects = _Lights(), []
    fake = types.SimpleNamespace(data=types.SimpleNamespace(
        lights=types.SimpleNamespace(new=lights.new, remove=lambda d: removed.append(d)),
        objects=types.SimpleNamespace(new=lambda name, data: types.SimpleNamespace(
            name=name, data=data, parent=None, matrix_world=None),
            remove=lambda obj, do_unlink=False: removed.append(obj))))
    monkeypatch.setattr(export_lights, "bpy", fake)
    matrix = types.SimpleNamespace(copy=lambda: "M")
    area = types.SimpleNamespace(name="Ash_Key", type="LIGHT", parent="arena_root", matrix_world=matrix,
                                 data=types.SimpleNamespace(name="Ash_Key", type="AREA", color=(0.5, 0.7, 1.0),
                                                            energy=4200.0, use_shadow=True))
    point = types.SimpleNamespace(name="Light", type="LIGHT", data=types.SimpleNamespace(type="POINT"))
    camera = types.SimpleNamespace(name="Camera", type="CAMERA")
    linked = []
    scene = types.SimpleNamespace(objects=[area, point, camera],
                                  collection=types.SimpleNamespace(objects=types.SimpleNamespace(link=linked.append)))
    with export_lights.staged_game_lights(["Ash_Key", "Light", "Camera", "Gone"], scene) as (staged, counts):
        spot = staged[0]
        assert spot.name == "Ash_Key_spot" and spot.data.type == "SPOT" and spot.parent == "arena_root"
        assert spot.matrix_world == "M" and spot.data.energy == 4200.0 and spot.data.color == (0.5, 0.7, 1.0)
        assert spot.data.spot_size == pytest.approx(2.0944) and linked == [spot]
        assert staged[1] is point and counts == {"lights": 2, "from_area": 1, "by_type": {"SPOT": 1, "POINT": 1}}
    assert removed == [spot, spot.data]  # stand-in object and light data freed; the area light untouched
    assert area.data.type == "AREA" and area.data.energy == 4200.0


def test_lane_carries_lights_only_for_a_game_spec_that_asks():
    source = (CHAT_CORE / "agent_export.py").read_text(encoding="utf-8")
    assert 'if spec.get("scene_lights"):' in source
    assert "staged_game_lights(spec.get(\"extra_object_names\"), scene)" in source
    assert 'overrides = {**(overrides or {}), "export_lights": True}' in source
    assert "lights_ctx.close()" in source
    from mixar.modules.space_mixie_chat.core import export_presets
    assert export_presets.preset_kwargs("game", "glb")["export_lights"] is False  # off unless asked

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contract v1.3 (boss fights): roles and params, the boss_fight settings,
rigged characters and their clips, and combat timing proven against the
exported clip timeline."""

import json
import struct
import types
from pathlib import Path

import pytest

from mixar.modules.game_studio.constants import PARAMS_PROP, ROLE_PROP
from mixar.modules.game_studio.core import auto_roles, characters, combat, roles, spec

FPS = 30.0


class Action:
    def __init__(self, name, start=1.0, end=91.0, markers=()):
        self.name, self.frame_range = name, (start, end)
        self.pose_markers = [types.SimpleNamespace(name=n, frame=f) for n, f in markers]


def _anim(*actions):
    strips = [types.SimpleNamespace(name=a.name.split("_")[-1], action=a) for a in actions]
    return types.SimpleNamespace(action=None, nla_tracks=[types.SimpleNamespace(strips=[s]) for s in strips])


@pytest.fixture
def boss_scene(make_obj, make_scene):
    """The user's file, shaped: a boss and a stand-in player under character
    roots, a preview rig of camera/lights + floor, a workspace root."""
    def character(prefix, clip_names, height):
        root = make_obj(f"{prefix}_character_Root", "EMPTY")
        rig = make_obj(f"{prefix.title()}_Rig", "ARMATURE", (2.9, 0.6, height), parent=root)
        skinned = make_obj(f"{prefix.title()}_Skinned", "MESH", (2.9, 1.0, height), parent=rig)
        skinned.parent_type, rig.parent_type = "OBJECT", "OBJECT"
        skinned.modifiers = [types.SimpleNamespace(type="ARMATURE", object=rig)]
        weapon_root = make_obj(f"{prefix}_glaive_Root", "EMPTY", parent=rig)
        weapon = make_obj(f"{prefix.title()}_Glaive", "MESH", (0.9, 0.2, 4.2), parent=weapon_root)
        weapon.modifiers = [types.SimpleNamespace(type="ARMATURE", object=rig)]
        rig.animation_data = _anim(*(Action(n, *frames) for n, frames in clip_names.items()))
        return [root, rig, skinned, weapon_root, weapon]

    boss = character("boss", {"boss_idle": (1, 121), "boss_walk": (1, 71),
                              "boss_attack_slam": (1, 91), "boss_attack_sweep": (1, 76),
                              "boss_death": (1, 121), "boss_presets_source_idle": (0, 460)}, 3.6)
    player = character("player", {"player_idle": (1, 121), "player_light_1": (1, 19),
                                  "player_light_x": (1, 19), "player_dodge": (1, 25)}, 1.8)
    preview = make_obj("boss_playback_preview_Root", "EMPTY")
    ground = make_obj("Preview_Ground", "MESH", (200.0, 200.0, 0.0), parent=preview)
    workspace = make_obj("WorkspaceRoot_5f98", "EMPTY")
    scene = make_scene(boss + player + [preview, ground, workspace])
    scene.render = types.SimpleNamespace(fps=30, fps_base=1.0)
    return scene


def _found(scene):
    return characters.find(roles.game_objects(scene))


# --- §1 roles and params -------------------------------------------------------

def test_v13_params_are_typed_and_bounded():
    clean, errors = roles.normalize_params({"hp": "800", "clip_prefix": "boss_", "display_name": "  Ash   Lord "})
    assert clean == {"hp": 800, "clip_prefix": "boss_", "display_name": "Ash Lord"} and errors == []
    assert roles.normalize_params({"hp": 0})[1] == ["param 'hp' must be between 1 and 100000"]
    assert roles.normalize_params({"hp": 100001})[1]
    assert roles.normalize_params({"clip_prefix": "boss-"})[1]
    assert roles.normalize_params({"clip_prefix": "x" * 33})[1]
    assert roles.normalize_params({"display_name": "x" * 41})[1]
    assert roles.normalize_params({"display_name": 5})[1] == ["param 'display_name' must be a string"]


def test_armatures_carry_roles_and_set_param_keeps_the_rest(make_obj):
    rig = make_obj("Boss_Rig", "ARMATURE")
    assert roles.set_role(rig, "boss", {"hp": 900}) == (True, [])
    assert roles.set_param(rig, "display_name", "Ash Lord") == []
    assert json.loads(rig[PARAMS_PROP]) == {"hp": 900, "display_name": "Ash Lord"}
    assert roles.set_param(rig, "hp", -1) and json.loads(rig[PARAMS_PROP])["hp"] == 900
    assert roles.set_param(make_obj("Rock"), "hp", 5) == ["'Rock' has no role"]


# --- §2 settings -------------------------------------------------------------------

def test_switching_to_boss_fight_sets_win_and_one_life_unless_asked():
    base = spec.DEFAULT_SETTINGS
    merged, errors = spec.merge_settings(base, {"template": "boss_fight"})
    assert errors == [] and merged["rules"]["win"] == "defeat_boss" and merged["rules"]["lives"] == 1
    for changes in ({"template": "boss_fight", "rules": {"lives": 3}},
                    {"rules": {"lives": 3}, "template": "boss_fight"}):  # either order
        merged, _ = spec.merge_settings(base, changes)
        assert merged["rules"]["lives"] == 3 and merged["rules"]["win"] == "defeat_boss"
    # Already a boss fight: a later change of lives is not undone.
    again, _ = spec.merge_settings(merged, {"template": "boss_fight", "title": "Ash"})
    assert again["rules"]["lives"] == 3
    # Leaving: a defeat_boss win (invalid elsewhere) falls back, unless asked.
    left, errors = spec.merge_settings(again, {"template": "third_person"})
    assert errors == [] and left["rules"]["win"] == "collect_all"
    kept, _ = spec.merge_settings(again, {"template": "top_down", "rules": {"win": "survive"}})
    assert kept["rules"]["win"] == "survive"


def test_combat_overrides_merge_validate_and_never_take_a_length():
    stored, errors = spec.merge_settings(spec.DEFAULT_SETTINGS, {"combat": {
        "clips": {"boss_attack_slam": {"hit": [0.93, 1.07], "damage": 35, "shape": "circle", "radius": 3.2}},
        "boss": {"phase2_at": 0.5}, "player": {"lock_on": True}}})
    assert errors == []
    merged, errors = spec.merge_settings(stored, {"combat": {"clips": {
        "boss_attack_slam": {"damage": 40, "length_s": 3.0, "shape": "cone", "hit": [1.2, 1.1]},
        "bad/name": {"hit": [0, 1]}}, "boss": {"phase2_at": 2}, "mood": 1}})
    slam = merged["combat"]["clips"]["boss_attack_slam"]
    assert slam == {"hit": [0.93, 1.07], "damage": 40, "shape": "circle", "radius": 3.2}
    assert len(errors) == 6 and any("length_s is measured" in e for e in errors)
    dropped, _ = spec.merge_settings(merged, {"combat": {"clips": {"boss_attack_slam": None}}})
    assert "clips" not in dropped["combat"] and dropped["combat"]["boss"] == {"phase2_at": 0.5}
    assert "combat" not in spec.build_spec(merged, [])  # overrides never ship raw


def _spec(template, nodes, win=None):
    settings, _ = spec.merge_settings(spec.DEFAULT_SETTINGS, {"template": template})
    if win:
        settings["rules"]["win"] = win
    return spec.build_spec(settings, [{"name": n, "role": r, "params": {}} for n, r in nodes])


def test_boss_validation():
    errors, _ = spec.validate_spec(_spec("third_person", [("Hero", "player"), ("Big", "boss"), ("G", "static")],
                                         win="defeat_boss"))
    assert any("boss role needs template boss_fight" in e for e in errors)
    assert any("defeat_boss needs template boss_fight" in e for e in errors)
    errors, _ = spec.validate_spec(_spec("boss_fight", [("Hero", "player"), ("G", "static")]))
    assert any(e.startswith("no boss") for e in errors)
    errors, _ = spec.validate_spec(_spec("boss_fight", [("Hero", "player"), ("A", "boss"), ("B", "boss")]))
    assert any("2 bosses" in e for e in errors)
    unrigged = [{"object": "Hero", "role": "player", "rig": False, "missing": [], "clip_prefix": "player_"},
                {"object": "A", "role": "boss", "rig": True, "missing": ["walk"], "clip_prefix": "boss_"}]
    errors, warnings = spec.validate_spec(_spec("boss_fight", [("Hero", "player"), ("A", "boss")]), unrigged)
    assert errors == ["Hero has no rig: a player needs an armature that deforms its mesh"]
    assert any("no boss_walk clip" in w for w in warnings)


# --- §3 characters and clips ---------------------------------------------------------

@pytest.mark.parametrize("clip,prefix,role,state", [
    ("boss_attack_slam", "boss_", "boss", "attack_*"), ("boss_roar", "boss_", "boss", "roar"),
    ("boss_presets_source_idle", "boss_", "boss", None), ("boss_attack_", "boss_", "boss", None),
    ("player_light_2", "player_", "player", "light_*"), ("player_light_x", "player_", "player", None),
    ("player_walk", "player_", "player", None), ("hero_dodge", "hero_", "player", "dodge"),
    ("idle", "boss_", "boss", None),
])
def test_classify(clip, prefix, role, state):
    assert characters.classify(clip, prefix, role) == state


def test_characters_find_rigs_clips_and_missing_states(boss_scene):
    boss_scene.objects.get("boss_character_Root")[ROLE_PROP] = "boss"
    boss_scene.objects.get("player_character_Root")[ROLE_PROP] = "player"
    found = {c["object"]: characters.public(c) for c in _found(boss_scene)}
    boss = found["boss_character_Root"]
    assert boss["rig"] and boss["rigs"] == ["Boss_Rig"]
    assert boss["clips"]["attack_*"] == ["boss_attack_slam", "boss_attack_sweep"]
    assert boss["missing"] == ["roar", "hit"]
    assert found["player_character_Root"]["clips"] == {"idle": ["player_idle"], "light_*": ["player_light_1"],
                                                       "dodge": ["player_dodge"]}
    clips = characters.export_clips(_found(boss_scene))
    assert "boss_presets_source_idle" not in clips and "player_light_x" not in clips
    assert clips == sorted(clips) and len(clips) == 8


def test_a_character_without_a_deforming_rig_has_no_rig(make_obj):
    root = make_obj("hero_Root", "EMPTY")
    rig = make_obj("Rig", "ARMATURE", parent=root)
    make_obj("Statue", "MESH", parent=root)  # not deformed
    assert characters.rigs([root, rig]) == []


# --- §2 combat timing ------------------------------------------------------------------

def test_markers_to_frames():
    marks = combat.marker_frames(Action("a", markers=[("hit_start", 28), ("hit_end", 32),
                                                      ("iframes_start", 3)]))
    assert marks["hit"] == (28.0, 32.0) and marks["iframes"] is None
    assert marks["problems"] == ["iframes: needs both iframes_start and iframes_end, iframes_start first"]
    assert combat.marker_frames(Action("a", markers=[("hit", 30)]))["hit"] == (30.0, None)


def test_prove_reads_the_rule_off_the_file():
    actions = {"slam": Action("slam", 1, 91), "slid": Action("slid", 1, 91), "odd": Action("odd", 1, 91)}
    timeline = {"slam": (1 / 30, 91 / 30), "slid": (0.0, 3.0), "odd": (1 / 30, 2.5)}
    proof = combat.prove(actions, timeline, FPS)
    assert proof["slam"]["proven"] and proof["slam"]["shift"] == 0.0 and proof["slam"]["max"] == 3.0333
    assert proof["slid"]["proven"] and proof["slid"]["shift"] == -0.0333  # exporter slid to zero
    assert not proof["odd"]["proven"]
    assert combat.prove({"gone": Action("gone")}, {}, FPS)["gone"]["in_file"] is False


def _tag(scene):
    scene.objects.get("boss_character_Root")[ROLE_PROP] = "boss"
    scene.objects.get("player_character_Root")[ROLE_PROP] = "player"


def _set_markers(scene, clip, markers):
    rig = next(o for o in scene.objects if getattr(o, "type", "") == "ARMATURE" and clip.startswith(
        o.name.split("_")[0].lower()))
    for track in rig.animation_data.nla_tracks:
        for strip in track.strips:
            if strip.action.name == clip:
                strip.action.pose_markers = [types.SimpleNamespace(name=n, frame=f) for n, f in markers]


def test_resolve_converts_markers_and_layers_overrides(boss_scene):
    _tag(boss_scene)
    _set_markers(boss_scene, "boss_attack_slam", [("hit_start", 28), ("hit_end", 32)])
    _set_markers(boss_scene, "player_dodge", [("iframes_start", 3), ("iframes_end", 15)])
    _set_markers(boss_scene, "player_light_1", [("hit", 7)])
    found = _found(boss_scene)
    overrides = {"clips": {"boss_attack_sweep": {"hit": [0.8, 0.93], "damage": 25},
                           "boss_attack_slam": {"damage": 35},
                           "boss_roar": {"hit": [0.1, 0.2]}},
                 "boss": {"phase2_at": 0.5}}
    block, sources, warnings = combat.resolve(found, overrides, FPS)
    assert block["clips"]["boss_attack_slam"] == {"length_s": 3.0333, "hit": [0.9333, 1.0667], "damage": 35}
    assert block["clips"]["boss_attack_sweep"] == {"length_s": 2.5333, "hit": [0.8, 0.93], "damage": 25}
    assert block["clips"]["player_dodge"] == {"length_s": 0.8333, "iframes": [0.1, 0.5]}
    assert block["clips"]["player_light_1"]["hit"] == [0.2333, 0.3533]  # single marker: +0.12 s
    assert "boss_idle" not in block["clips"]  # nothing given → left out, never invented
    assert block["boss"] == {"phase2_at": 0.5}
    assert sources == {"boss_attack_slam": "markers", "boss_attack_sweep": "configured",
                       "player_light_1": "markers", "player_dodge": "markers"}
    assert warnings == ["combat.clips.boss_roar: no exported character clip has that name"]


def test_resolve_drops_windows_the_file_disproves_or_that_overrun(boss_scene):
    _tag(boss_scene)
    _set_markers(boss_scene, "boss_attack_slam", [("hit_start", 28), ("hit_end", 32)])
    found = _found(boss_scene)
    actions = {n: a for c in found for n, a in c["actions"].items()}
    timeline = {n: (a.frame_range[0] / FPS, a.frame_range[1] / FPS) for n, a in actions.items()}
    timeline["boss_attack_slam"] = (1 / FPS, 2.0)  # the file disagrees with frames / fps
    proof = combat.prove(actions, timeline, FPS)
    overrides = {"clips": {"player_dodge": {"iframes": [0.1, 5.0]}}}
    block, _sources, warnings = combat.resolve(found, overrides, FPS, proof)
    assert "boss_attack_slam" not in block["clips"] and "player_dodge" not in block["clips"]
    assert any("marker timing left out" in w for w in warnings)
    assert any("player_dodge: iframes" in w and "outside the clip" in w for w in warnings)


# --- auto-assign ---------------------------------------------------------------------------

def test_auto_roles_casts_rigged_characters_under_boss_fight(boss_scene):
    objects = roles.game_objects(boss_scene)
    got = {s["object"]: s["role"] for s in auto_roles.suggest_roles(objects, template="boss_fight")}
    assert got == {"boss_character_Root": "boss", "player_character_Root": "player",
                   "boss_playback_preview_Root": "static"}
    # Other templates keep v1 behaviour: no boss, "character" still names a player.
    plain = {s["object"]: s["role"] for s in auto_roles.suggest_roles(objects)}
    assert "boss" not in plain.values()


def test_auto_roles_tallest_is_the_boss_without_names_and_keeps_user_casting(boss_scene):
    boss_scene.objects.get("boss_character_Root").name = "a_Root"
    boss_scene.objects.get("player_character_Root").name = "b_Root"
    objects = roles.game_objects(boss_scene)
    got = {s["object"]: s["role"] for s in auto_roles.suggest_roles(objects, template="boss_fight")}
    assert got["a_Root"] == "boss" and got["b_Root"] == "player"
    boss_scene.objects.get("b_Root")[ROLE_PROP] = "boss"  # the user decided otherwise
    got = {s["object"]: s["role"] for s in auto_roles.suggest_roles(objects, template="boss_fight")}
    assert got["a_Root"] == "player" and "b_Root" not in got


# --- export -------------------------------------------------------------------------------

def test_read_timeline_from_a_glb(tmp_path):
    from mixar.modules.game_studio.core import exporter
    doc = {"accessors": [{"min": [1 / 30], "max": [91 / 30]}, {"min": [0.0], "max": [1.0]}],
           "animations": [{"name": "boss_attack_slam", "samplers": [{"input": 0}]},
                          {"name": "other", "samplers": [{"input": 1}, {"input": 0}]}]}
    body = json.dumps(doc).encode()
    body += b" " * (-len(body) % 4)
    path = tmp_path / "scene.glb"
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(body)) + struct.pack("<I", len(body))
                     + b"JSON" + body)
    timeline = exporter.read_timeline(str(path))
    assert timeline["boss_attack_slam"] == pytest.approx((1 / 30, 91 / 30))
    assert timeline["other"] == pytest.approx((0.0, 91 / 30))
    (tmp_path / "bad.glb").write_bytes(b"nope")
    with pytest.raises(ValueError):
        exporter.read_timeline(str(tmp_path / "bad.glb"))


def test_export_spec_carries_rigs_and_an_explicit_clip_selection(boss_scene):
    from mixar.modules.game_studio.core import exporter
    objects = roles.game_objects(boss_scene)
    lane = exporter.export_spec(objects, ["boss_idle"])
    assert "Boss_Rig" in lane["extra_object_names"] and "boss_character_Root" in lane["extra_object_names"]
    assert lane["animations"] == ["boss_idle"]
    assert "animations" not in exporter.export_spec(objects)  # v1 templates: every clip, as before
    assert exporter.export_spec(objects, [])["animations"] == []


def test_game_scene_objects_stage_a_named_rig():
    from mixar.modules.space_mixie_chat.core.export_web import game_scene_objects

    class NS:  # hashable, like a Blender object
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    root = NS(name="boss_character_Root", type="EMPTY", parent=None)
    rig = NS(name="Boss_Rig", type="ARMATURE", parent=root)
    mesh = NS(name="Boss_Skinned", type="MESH", parent=rig)
    scene = NS(objects=[root, rig, mesh])
    assert game_scene_objects([mesh], ["Boss_Rig"], scene) == {root, rig}


def test_time_base_matches_the_forks_measurement_on_the_user_glb():
    """fork-boss measured the user's GLB: sampler inputs start at 1/30 s, so
    t = frame / 30 (slam impact frame 29 = 0.967 s, sweep contact frame 26 =
    0.867 s). The client's proof derives the same rule from the file."""
    actions = {"boss_attack_slam": Action("boss_attack_slam", 1, 91),
               "boss_attack_sweep": Action("boss_attack_sweep", 1, 76)}
    timeline = {"boss_attack_slam": (1 / 30, 91 / 30), "boss_attack_sweep": (1 / 30, 76 / 30)}
    proof = combat.prove(actions, timeline, FPS)
    for name, frame, seconds in (("boss_attack_slam", 29, 0.967), ("boss_attack_sweep", 26, 0.867)):
        assert proof[name]["proven"] and proof[name]["shift"] == 0.0
        assert round(frame / FPS + proof[name]["shift"], 3) == seconds


def test_post_install_selftest_allows_a_boss_fight():
    """A boss_fight self-test plays a scripted fight (~20 s real time)."""
    from mixar.modules.game_studio.core import library_install
    assert library_install.SELFTEST_TIMEOUT_S >= 30


# --- character rigs never move as objects in a clip -----------------------------------

def _glb(tmp_path, doc, binary=b"\0" * 16):
    body = json.dumps(doc).encode()
    body += b" " * (-len(body) % 4)
    bin_chunk = struct.pack("<I", len(binary)) + b"BIN\0" + binary
    path = tmp_path / "scene.glb"
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + 8 + len(body) + len(bin_chunk))
                     + struct.pack("<I", len(body)) + b"JSON" + body + bin_chunk)
    return path


def test_rig_object_motion_is_stripped_and_bones_kept(tmp_path):
    from mixar.modules.game_studio.core import exporter
    doc = {"nodes": [{"name": "Player_Rig"}, {"name": "R_Hand"}, {"name": "Boss_Rig"}],
           "accessors": [{"min": [0.0], "max": [1.0]}] * 6,
           "animations": [{"name": "player_run",
                           "samplers": [{"input": 0, "output": i} for i in range(1, 5)],
                           "channels": [{"sampler": 0, "target": {"node": 0, "path": "rotation"}},
                                        {"sampler": 1, "target": {"node": 1, "path": "rotation"}},
                                        {"sampler": 2, "target": {"node": 0, "path": "translation"}},
                                        {"sampler": 3, "target": {"node": 1, "path": "translation"}}]}]}
    path = _glb(tmp_path, doc)
    assert exporter.strip_rig_object_motion(str(path), ["Player_Rig", "Boss_Rig"]) == 2
    data = path.read_bytes()
    length = struct.unpack("<I", data[12:16])[0]
    assert struct.unpack("<I", data[8:12])[0] == len(data)
    out = json.loads(data[20:20 + length])
    anim = out["animations"][0]
    assert [c["target"] for c in anim["channels"]] == [{"node": 1, "path": "rotation"},
                                                       {"node": 1, "path": "translation"}]
    assert [c["sampler"] for c in anim["channels"]] == [0, 1] and [s["output"] for s in anim["samplers"]] == [2, 4]
    assert data[20 + length:].startswith(struct.pack("<I", 16) + b"BIN\0")
    assert exporter.read_timeline(str(path))["player_run"] == (0.0, 1.0)
    assert exporter.strip_rig_object_motion(str(path), ["Player_Rig"]) == 0  # idempotent


def test_a_prefixed_camera_action_is_never_a_character_clip(make_obj):
    """A preview camera's object action named like a clip
    (``player_stride_rebuild_Camera.001Action``) is not a state, and is not
    on the rig, so it is never exported or played on the character."""
    from test_game_studio_arena_feel import _rig_with
    root, subtree = _rig_with(["player_idle", "player_run"], make_obj)
    camera_action = types.SimpleNamespace(name="player_stride_rebuild_Camera.001Action", frame_range=(1, 145),
                                          pose_markers=[])
    camera = make_obj("player_stride_rebuild_Camera.001", "CAMERA")
    camera.animation_data = types.SimpleNamespace(action=camera_action, nla_tracks=[])
    assert characters.classify(camera_action.name, "player_", "player") is None
    found = characters.describe(root, "player", {}, subtree + [camera])
    assert "player_stride_rebuild_Camera.001Action" not in characters.export_clips([found])
    assert sorted(found["actions"]) == ["player_idle", "player_run"]


def test_boss_fight_export_strips_rig_object_motion_before_the_timeline_proof():
    source = (Path(__file__).parents[2] / "src/scripts/mixar/modules/game_studio/core/exporter.py").read_text()
    body = source[source.index("def write_package("):]
    assert body.index("strip_rig_object_motion(glb, rigs)") < body.index("_prove_combat(scene, checked, glb")

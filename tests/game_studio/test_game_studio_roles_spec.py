# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Roles (contract §1) and ``mixar_game_spec_v1`` (contract §2)."""

import json

import pytest

from mixar.modules.game_studio.constants import PARAMS_PROP, ROLE_PROP, SPEC_PROP
from mixar.modules.game_studio.core import roles, spec


@pytest.mark.parametrize("name,kind,dims,expected", [
    ("Hero", "MESH", (1, 1, 2), "player"),
    ("PlayerCharacter", "MESH", (1, 1, 2), "player"),
    ("GoldCoin.001", "MESH", (0.3, 0.3, 0.05), "collectible"),
    ("Gems", "MESH", (0.3, 0.3, 0.3), "collectible"),
    ("star_pickup", "MESH", (0.3, 0.3, 0.3), "collectible"),
    ("Goal Flag", "MESH", (0.2, 0.2, 3), "goal"),
    ("ExitPortal", "MESH", (2, 0.2, 3), "goal"),
    ("Spikes", "MESH", (1, 1, 0.5), "hazard"),
    ("LavaPool", "MESH", (3, 3, 0.1), "hazard"),
    ("Enemy.002", "MESH", (1, 1, 2), "enemy"),
    ("Monster", "MESH", (1, 1, 2), "enemy"),
    ("Crate", "MESH", (1, 1, 1), "prop"),
    ("Cloud", "MESH", (4, 2, 1), "decor"),
    ("Ground", "MESH", (40, 40, 0.2), "static"),
    ("Lava Floor", "MESH", (40, 40, 0.2), "static"),  # the whole level stays solid
    ("PlayerSpawn", "EMPTY", (0, 0, 0), "spawn"),
    ("Rock", "MESH", (1, 1, 1), None),
    ("HeroLight", "LIGHT", (0, 0, 0), None),
])
def test_suggest_role_heuristics(name, kind, dims, expected):
    assert roles.suggest_role(name, kind, dims)[0] == expected


def test_suggest_roles_keeps_explicit_roles_and_one_player(make_obj):
    tagged = make_obj("Hero")
    tagged[ROLE_PROP] = "enemy"
    objects = [tagged, make_obj("Player"), make_obj("Character"), make_obj("Coin")]
    suggestions = {s["object"]: s["role"] for s in roles.suggest_roles(objects)}
    assert "Hero" not in suggestions  # explicit role kept
    assert suggestions["Player"] == "player"
    assert suggestions["Character"] is None  # exactly one player
    assert suggestions["Coin"] == "collectible"


def test_set_role_validates_and_stores_json_params(make_obj):
    obj = make_obj("Gem")
    applied, errors = roles.set_role(obj, "collectible", {"value": "5", "bogus": 1})
    assert applied and errors == ["unknown param 'bogus'"]
    assert obj[ROLE_PROP] == "collectible"
    assert json.loads(obj[PARAMS_PROP]) == {"value": 5}
    assert roles.set_role(obj, "wizard") == (False, ["unknown role 'wizard'"])
    assert obj[ROLE_PROP] == "collectible"
    assert roles.set_role(make_obj("Lamp", "LIGHT"), "static")[0] is False
    roles.set_role(obj, None)
    assert ROLE_PROP not in obj and PARAMS_PROP not in obj


def test_normalize_params_rejects_bools_nan_and_junk():
    assert roles.normalize_params({"speed": True})[1]
    assert roles.normalize_params({"speed": float("nan")})[1]
    assert roles.normalize_params("not json")[1] == ["params are not valid JSON"]
    assert roles.normalize_params('{"damage": 2, "speed": 1}') == ({"damage": 2, "speed": 1.0}, [])


def test_effective_role_and_in_game(make_obj):
    mesh, empty, ignored, hidden = (make_obj("Rock"), make_obj("Group", "EMPTY"),
                                    make_obj("Ref"), make_obj("Hidden", visible=False))
    ignored[ROLE_PROP] = "ignore"
    assert roles.effective_role(mesh) == "static"
    assert roles.effective_role(empty) is None
    assert roles.in_game(mesh) and not roles.in_game(empty)
    assert not roles.in_game(ignored) and not roles.in_game(hidden)


def _level(make_obj):
    hero, coin, ground, ref = make_obj("Hero"), make_obj("Coin.001"), make_obj("Ground"), make_obj("Ref")
    hero[ROLE_PROP] = "player"
    coin[ROLE_PROP] = "collectible"
    coin[PARAMS_PROP] = '{"value": 2}'
    ref[ROLE_PROP] = "ignore"
    return [hero, coin, ground, ref]


def test_build_spec_matches_contract_shape(make_obj):
    nodes = spec.build_nodes(_level(make_obj))
    assert nodes == [
        {"name": "Hero", "role": "player", "params": {}},
        {"name": "Coin.001", "role": "collectible", "params": {"value": 2}},
        {"name": "Ground", "role": "static", "params": {}},
    ]
    built = spec.build_spec(spec.DEFAULT_SETTINGS | {"title": "Crystal Run"}, nodes, "1.2.3")
    assert list(built)[0] == "schema" and built["schema"] == "mixar_game_spec_v1"
    assert built["slug"] == "crystal-run"
    assert built["scene_file"] == "scene.glb" and built["up_axis"] == "Y"
    assert built["generator"] == {"app": "Mixar", "version": "1.2.3"}
    assert set(built) >= {"title", "template", "rules", "player", "camera", "world", "ui", "nodes"}
    assert spec.validate_spec(built) == ([], [])
    json.dumps(built)


def test_validate_spec_rules(make_obj):
    base = spec.build_spec(spec.DEFAULT_SETTINGS, [{"name": "Ground", "role": "static", "params": {}}])
    errors, _ = spec.validate_spec(base)
    assert any("no player" in e for e in errors)
    assert any("collect_all" in e for e in errors)
    two = dict(base, nodes=[{"name": "A", "role": "player"}, {"name": "B", "role": "player"},
                            {"name": "G", "role": "goal"}], rules={"win": "reach_goal"})
    errors, warnings = spec.validate_spec(two)
    assert errors == ["2 players (A, B); exactly one is allowed"]
    assert "no static geometry" in warnings[0]
    survive = dict(base, nodes=[{"name": "A", "role": "player"}], rules={"win": "survive", "time_limit_s": 0})
    assert "survive" in spec.validate_spec(survive)[0][0]


def test_merge_settings_validates_each_field():
    merged, errors = spec.merge_settings(spec.DEFAULT_SETTINGS, {
        "title": "  My   Game ", "template": "platformer", "rules": {"win": "score", "target_score": 10,
                                                                    "lives": -1},
        "player": {"move_speed": "8"}, "camera": {"zoom": 2}, "ui": {"show_timer": "yes"},
        "colour": "red"})
    assert merged["title"] == "My Game" and merged["template"] == "platformer"
    assert merged["rules"]["win"] == "score" and merged["rules"]["target_score"] == 10
    assert merged["rules"]["lives"] == 3 and merged["player"]["move_speed"] == 8.0
    assert len(errors) == 4  # lives, camera.zoom, ui.show_timer, colour
    assert spec.DEFAULT_SETTINGS["title"] == "Untitled Game"  # never mutated


def test_settings_round_trip_through_scene_json(make_scene):
    scene = make_scene()
    assert spec.load_settings(scene) == spec.DEFAULT_SETTINGS
    merged, _ = spec.merge_settings(spec.load_settings(scene), {"title": "Run"})
    spec.save_settings(scene, merged)
    assert json.loads(scene[SPEC_PROP])["title"] == "Run"
    assert spec.load_settings(scene)["title"] == "Run"
    scene[SPEC_PROP] = "{broken"
    assert spec.load_settings(scene) == spec.DEFAULT_SETTINGS


def test_platform_and_store_page_validation():
    assert spec.validate_platforms(None) == (["web"], [])
    assert spec.validate_platforms(["web", "WEB", "linux"]) == (["web", "linux"], [])
    assert spec.validate_platforms(["ps5"])[1]
    page, errors = spec.normalize_store_page({"tagline": "x" * 300, "genres": "Platformer",
                                              "tags": ["Cute", "cute", " Coins "], "price_cents": -1,
                                              "extra": 1})
    assert len(page["tagline"]) == 140 and page["genres"] == ["platformer"]
    assert len(spec.normalize_store_page({"genres": [str(i) for i in range(20)]})[0]["genres"]) == 8
    assert page["tags"] == ["cute", "coins"] and page["price_cents"] == 0
    assert len(errors) == 2
    assert spec.slugify("  Crystal Run!! 2 ") == "crystal-run-2" and spec.slugify("!!!") == "game"
    assert spec.normalize_store_page({"price_cents": 50})[1]  # 0 or >= 100
    assert spec.normalize_store_page({"price_cents": 499})[0]["price_cents"] == 499
    assert spec.slugify("Go") == "go-game"  # the store wants >= 3 characters
    assert spec.normalize_store_page({"content_rating": "adults"})[1]
    assert spec.normalize_store_page({"content_rating": "teen"})[0]["content_rating"] == "teen"

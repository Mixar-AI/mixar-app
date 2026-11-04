# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""``engine_assets``: the engine project's own assets (Fab, Marketplace) found
by name and placed — Unreal through Epic's EditorToolset beside Mixar Link,
Godot through Mixar Link's list_files (a fake MCP server; no engine)."""

import json
import os
import sys
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import engine_assets as ea  # noqa: E402
from mixar.modules.space_mixie_chat.core import engine_link as el  # noqa: E402

TREES = "/Game/Megaplant_Library/Tree_Goat_Willow/Tree_Goat_Willow_01"
TWIGS = "/Game/Megaplant_Library/Tree_Goat_Willow/Instances"
REGISTRY = {  # path -> class, as the live 5.8 project answered
    f"{TREES}/Tree_Goat_Willow_01_A": "SkeletalMesh",
    f"{TREES}/Tree_Goat_Willow_01_B": "SkeletalMesh",
    f"{TREES}/Tree_Goat_Willow_01_A_Skeleton": "Skeleton",
    f"{TWIGS}/Branch_Goat_Willow_01": "StaticMesh",
    f"{TWIGS}/Twig_Goat_Willow_Up_01": "StaticMesh",
    "/Game/LevelPrototyping/Meshes/SM_Cube": "StaticMesh",
    "/Game/ThirdPerson/Lvl_ThirdPerson": "World",
}
CLASS_OF = {"/Script/Engine.StaticMesh": "StaticMesh", "/Script/Engine.SkeletalMesh": "SkeletalMesh",
            "/Script/Engine.Actor": "Blueprint", "/Script/Engine.World": "World"}
INFO = {"engine": "unreal", "transport": "unreal_mcp"}


def _reply(value=None, error=None):
    if error:
        return {"isError": True, "content": [{"type": "text", "text": error}]}
    return {"content": [{"type": "text", "text": json.dumps({"returnValue": value})}]}


def _mixar(data=None, error=None):
    body = {"ok": False, "error": error} if error else {"ok": True, "data": data or {}}
    return {"content": [{"type": "text", "text": json.dumps({"returnValue": json.dumps(body)})}]}


class FakeUnreal(el.UnrealMcpClient):
    """Unreal's MCP server: Epic's toolsets and Mixar Link's, by toolset."""

    def __init__(self, mode="plugin", playing=False, level="/Game/ThirdPerson/Lvl_ThirdPerson",
                 dirty=False, open_world=False, timeout_on="", spawn_then_time_out=False):
        super().__init__(9880, "/mcp", "mixar_link.toolsets.MixarLinkTools")
        self.mode, self.playing, self.level = mode, playing, level
        self.calls, self.actors = [], []
        # Package dirty flags (is_dirty), as Unreal keeps them; an Open World level keeps its actors outside.
        self.dirty = {level.split(".", 1)[0]} if dirty else set()
        self.open_world = open_world
        # A call that does not answer in time (urllib's read timeout), after doing its work when asked.
        self.timeout_on, self.spawn_then_time_out = timeout_on, spawn_then_time_out

    def initialize(self, timeout=10.0):
        self.session = "s"
        return {}

    def _rpc(self, method, params, timeout):
        assert method == "tools/call" and params["name"] == "call_tool"
        args = params["arguments"]
        toolset, tool, a = args["toolset_name"], args["tool_name"], args["arguments"]
        self.calls.append((toolset.rsplit(".", 1)[-1], tool, a))
        if tool == self.timeout_on:
            if self.spawn_then_time_out:
                self._answer(toolset, tool, a)
            raise el._unanswered(TimeoutError("timed out"))
        return 200, {}, {"result": self._answer(toolset, tool, a)}

    def _answer(self, toolset, tool, a):
        if toolset == self.toolset:
            if tool == "status":
                return _mixar({"project_mode": self.mode, "playing": self.playing, "edited_scene": self.level})
            if tool == "save_scene":
                return _mixar({"saved": True}) if self.mode == "owned" else _mixar(error="plugin mode: no")
            return _mixar({})
        if tool == "find_assets":
            ref = (a.get("asset_type") or {}).get("refPath")
            want = CLASS_OF.get(ref, "?") if ref else None  # another class: nothing of it here
            assert "name" in a  # Unreal's schema requires every string argument
            return _reply([p for p, c in REGISTRY.items() if p.startswith(a["folder_path"])
                           and a["name"].lower() in p.rsplit("/", 1)[-1].lower() and (want in (None, c))])
        if tool == "get_asset_class":
            return _reply(REGISTRY.get(a["asset_path"]))
        if tool == "list_folders":
            if "/__ExternalActors__/" in a["root_path"]:
                return _reply([a["root_path"] + "/0/"] if self.open_world else [])
            return _reply(["/Game/Megaplant_Library/", "/Game/__ExternalActors__/", "/Game/ThirdPerson/"])
        if tool == "is_dirty":
            assert set(a) == {"asset_path"}
            return _reply(a["asset_path"] in self.dirty)
        if tool == "exists":
            return _reply(a["path"] in REGISTRY)
        if tool == "get_current_level":
            return _reply(self.level)
        if tool == "find_actors":
            assert a["tag"] == "" and a["collision_channels"] == []
            return _reply([{"refPath": f"L:{n}"} for n in self.actors if a["name"].lower() in n.lower()])
        if tool == "add_to_scene_from_asset":
            self.actors.append(a["name"])
            if not self.open_world:  # an Open World actor dirties its own package, not the level's
                self.dirty.add(self.level.split(".", 1)[0])
            return _reply({"refPath": f"L:{a['name']}"})
        if tool == "save_assets":
            self.dirty -= set(a["asset_paths"])
            return _reply(True)
        return _reply(error=f"unknown tool {tool}")


def _call(client, tool, args, info=INFO):
    return ea.run(info, client, tool, args, 30.0)


def test_a_search_finds_the_fab_trees_by_name_with_their_kind():
    out = _call(FakeUnreal(), "assets", {"query": "willow tree"})
    assert out["success"]
    data = out["data"]
    # The trees (skeletal meshes) lead; the pack's branches follow; skeletons are not placeable.
    assert [a["name"] for a in data["assets"][:2]] == ["Tree_Goat_Willow_01_A", "Tree_Goat_Willow_01_B"]
    assert {a["kind"] for a in data["assets"]} == {"skeletal_mesh", "static_mesh"}
    assert not any(a["name"].endswith("_Skeleton") for a in data["assets"])
    assert {g["folder"] for g in data["groups"]} == {TREES, TWIGS}
    # The project's structure: subfolders, never the engine's per-actor files.
    assert "/Game/Megaplant_Library" in data["folders"] and not any("__External" in f for f in data["folders"])


def test_every_word_must_be_in_the_path_and_a_typed_search_names_its_class():
    client = FakeUnreal()
    out = _call(client, "assets", {"query": "cube willow"})
    assert out["data"]["assets"] == []
    typed = [c for c in client.calls if c[1] == "find_assets"]
    assert {c[2]["asset_type"]["refPath"] for c in typed} >= {"/Script/Engine.StaticMesh",
                                                              "/Script/Engine.SkeletalMesh"}
    assert all(c[2]["name"] == "willow" for c in typed)  # the longest word goes to the registry


def test_kind_any_classifies_each_match():
    out = _call(FakeUnreal(), "assets", {"query": "lvl", "kind": "any"})
    assert out["data"]["assets"] == [{"path": "/Game/ThirdPerson/Lvl_ThirdPerson", "name": "Lvl_ThirdPerson",
                                      "kind": "level"}]


def test_bad_arguments_are_refused_with_the_fix():
    assert "content path" in _call(FakeUnreal(), "assets", {"folder": "Megaplant"})["error"]
    assert "kind must be" in _call(FakeUnreal(), "assets", {"kind": "trees"})["error"]


def test_place_spawns_in_unreals_frame_and_saves_in_plugin_mode():
    client = FakeUnreal(mode="plugin")
    out = _call(client, "place", {"scene": f"{TREES}/Tree_Goat_Willow_01_A", "position": [2, 3, 0.5],
                                  "yaw_deg": 30, "scale": 2, "snap_to_ground": True})
    assert out["success"], out
    spawn = next(c[2] for c in client.calls if c[1] == "add_to_scene_from_asset")
    assert spawn["xform"]["location"] == {"x": 200.0, "y": -300.0, "z": 50.0}  # Blender m -> Unreal cm, Y flipped
    assert spawn["xform"]["rotation"]["yaw"] == -30.0 and spawn["xform"]["scale"]["x"] == 2.0
    assert spawn["name"] == "Tree_Goat_Willow_01_A" and spawn["snap_to_ground"] is True
    # Mixar Link refuses to save the user's own level; Epic's save_assets saves THAT level only,
    # never the empty list (Unreal's Save All would write the user's other unsaved work too).
    after_spawn = [c[1] for c in client.calls]
    after_spawn = after_spawn[after_spawn.index("add_to_scene_from_asset") + 1:]
    assert after_spawn == ["save_scene", "list_folders", "is_dirty", "save_assets"]
    saves = [c[2]["asset_paths"] for c in client.calls if c[1] == "save_assets"]
    assert saves == [["/Game/ThirdPerson/Lvl_ThirdPerson"]] and [] not in saves
    assert out["data"]["saved"] and "Saved only the level" in out["data"]["note"]
    # The level was clean before the place (read before the spawn) and the place dirtied it.
    assert [c[1] for c in client.calls].index("is_dirty") < [c[1] for c in client.calls].index(
        "add_to_scene_from_asset")


def test_a_level_with_the_users_unsaved_changes_is_placed_into_but_never_saved():
    client = FakeUnreal(mode="plugin", dirty=True)
    out = _call(client, "place", {"scene": "/Game/LevelPrototyping/Meshes/SM_Cube"})
    assert out["success"] and client.actors == ["SM_Cube"]
    assert out["data"]["saved"] is False and "unsaved changes of the user's" in out["data"]["note"]
    assert "save_assets" not in [c[1] for c in client.calls]


def test_without_a_readable_dirty_flag_plugin_mode_never_saves():
    client = FakeUnreal(mode="plugin")
    answer = client._answer
    client._answer = lambda t, tool, a: _reply(error="Unknown tool is_dirty") if tool == "is_dirty" else \
        answer(t, tool, a)
    out = _call(client, "place", {"scene": "/Game/LevelPrototyping/Meshes/SM_Cube"})
    assert out["success"] and out["data"]["saved"] is False and "could not say" in out["data"]["note"]
    assert "save_assets" not in [c[1] for c in client.calls]


def test_an_open_world_level_is_not_claimed_saved():
    client = FakeUnreal(mode="plugin", open_world=True)
    out = _call(client, "place", {"scene": "/Game/LevelPrototyping/Meshes/SM_Cube"})
    assert out["success"] and out["data"]["saved"] is False and "Open World" in out["data"]["note"]
    assert "save_assets" not in [c[1] for c in client.calls]
    probe = next(c[2] for c in client.calls if c[1] == "list_folders")
    assert probe["root_path"] == "/Game/__ExternalActors__/ThirdPerson/Lvl_ThirdPerson"


@pytest.mark.parametrize("timeout_on", ["add_to_scene_from_asset", "save_scene", "save_assets"])
def test_a_timeout_from_the_spawn_on_says_the_placement_may_have_completed(timeout_on):
    client = FakeUnreal(mode="plugin", timeout_on=timeout_on, spawn_then_time_out=True)
    out = _call(client, "place", {"scene": "/Game/LevelPrototyping/Meshes/SM_Cube"})
    assert client.actors == ["SM_Cube"]  # Unreal made the actor; the answer never came
    assert out == {"success": False, "error": el.PLACE_TIMED_OUT}
    assert "engine_scene_tree" in out["error"] and "may still have completed" in out["error"]


@pytest.mark.parametrize("timeout_on", ["status", "exists", "find_actors", "is_dirty"])
def test_a_timeout_before_the_spawn_is_a_plain_failure(timeout_on):
    client = FakeUnreal(mode="plugin", timeout_on=timeout_on)
    out = _call(client, "place", {"scene": "/Game/LevelPrototyping/Meshes/SM_Cube"})
    assert not out["success"] and out["error"] == "The engine did not answer (TimeoutError)."
    assert client.actors == [] and "add_to_scene_from_asset" not in [c[1] for c in client.calls]


def test_mixar_links_own_place_that_times_out_may_have_completed(monkeypatch):
    client = FakeUnreal(timeout_on="place")
    monkeypatch.setattr(el, "_connect", lambda engine: (INFO, client))
    assert el.link_call.__wrapped__("place", {"scene": "/Game/Mixar/Crate"}) == \
        {"success": False, "error": el.PLACE_TIMED_OUT}
    client.timeout_on = "scene_tree"  # any other call's timeout stays a plain failure
    assert el.link_call.__wrapped__("scene_tree", {})["error"] == "The engine did not answer (TimeoutError)."


def test_an_object_path_level_is_saved_as_its_package():
    client = FakeUnreal(level="/Game/ThirdPerson/Lvl_ThirdPerson.Lvl_ThirdPerson")
    out = _call(client, "place", {"scene": "/Game/LevelPrototyping/Meshes/SM_Cube"})
    assert out["data"]["saved"]
    assert [c[2]["asset_paths"] for c in client.calls if c[1] == "save_assets"] == \
        [["/Game/ThirdPerson/Lvl_ThirdPerson"]]


def test_an_owned_project_saves_through_mixar_link_only():
    client = FakeUnreal(mode="owned")
    out = _call(client, "place", {"scene": f"{TWIGS}/Branch_Goat_Willow_01"})
    assert out["data"]["saved"] and "note" not in out["data"]
    assert "save_assets" not in [c[1] for c in client.calls]


def test_a_second_instance_gets_its_own_label():
    client = FakeUnreal()
    for _ in range(2):
        _call(client, "place", {"scene": "/Game/LevelPrototyping/Meshes/SM_Cube"})
    assert client.actors == ["SM_Cube", "SM_Cube_2"]


@pytest.mark.parametrize("client, args, said", [
    (FakeUnreal(playing=True), {"scene": "/Game/LevelPrototyping/Meshes/SM_Cube"}, "stop it first"),
    (FakeUnreal(level="/Temp/Untitled_1"), {"scene": "/Game/LevelPrototyping/Meshes/SM_Cube"}, "never saved"),
    (FakeUnreal(), {"scene": "/Game/Nope/SM_Gone"}, "engine_assets"),
])
def test_place_refusals_say_what_to_do(client, args, said):
    out = _call(client, "place", args)
    assert not out["success"] and said in out["error"]
    assert "add_to_scene_from_asset" not in [c[1] for c in client.calls]


def test_routing_keeps_mixar_packages_and_godot_on_mixar_link():
    assert ea.handles(INFO, "assets", {}) and ea.handles({"engine": "godot"}, "assets", {})
    assert ea.handles(INFO, "place", {"scene": "/Game/Megaplant_Library/Tree"})
    assert not ea.handles(INFO, "place", {"scene": "/Game/Mixar/Crate"})
    assert not ea.handles({"engine": "godot"}, "place", {"scene": "res://Fab/tree.glb"})
    assert ea.adapter_args("place", {"scene": "/Game/Mixar/Crate", "scale": 2, "snap_to_ground": True}) == \
        {"scene": "/Game/Mixar/Crate"}
    assert "assets" in el.CALLABLE_TOOLS and ea.tools_with_assets(["status"]) == ["status", "assets"]


def test_link_call_routes_through_engine_assets(monkeypatch):
    client = FakeUnreal()
    monkeypatch.setattr(el, "_connect", lambda engine: (INFO, client))
    out = el.link_call.__wrapped__("assets", {"query": "cube"})
    assert out["success"] and out["data"]["assets"][0]["name"] == "SM_Cube"


def test_an_epic_toolset_that_is_off_says_to_reconnect():
    client = FakeUnreal()
    client._answer = lambda *a: _reply(error="Toolset 'editor_toolset.toolsets.asset.AssetTools' not found")
    assert "reconnect" in _call(client, "assets", {"query": "x"})["error"]


class FakeGodot:
    def __init__(self, files):
        self.files = files

    def call(self, name, arguments, timeout):
        assert name == "list_files" and arguments["dir"] == "res://"
        data = {"dir": "res://", "files": [{"path": p, "bytes": -1} for p in self.files], "truncated": False}
        return {"structuredContent": data}


def test_godot_searches_scenes_and_models_outside_its_own_addon():
    client = FakeGodot(["res://Fab/Rocks/rock_big.glb", "res://Fab/Rocks/rock_big.png", "res://levels/Main.tscn",
                        "res://addons/mixar_link/templates/rock.tscn", "res://Fab/Trees/oak.fbx"])
    out = _call(client, "assets", {"query": "rock"}, info={"engine": "godot"})
    assert out["data"]["assets"] == [{"path": "res://Fab/Rocks/rock_big.glb", "name": "rock_big", "kind": "model"}]
    overview = _call(client, "assets", {}, info={"engine": "godot"})["data"]
    assert overview["folders"] == ["res://Fab", "res://addons", "res://levels"] and overview["total"] == 3

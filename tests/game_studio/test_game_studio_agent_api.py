# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent API shapes (contract §5), confirm gating, and the build / export /
publish jobs end to end against the fake fork and a stub store."""

import json
import os
import sys
import time

import pytest

from mixar.modules.game_studio.constants import ROLE_PROP, STORE_PROP
from mixar.modules.game_studio.core import agent_api, exporter, jobs, pipeline

from test_game_studio_store_client import _envelope, stub  # noqa: F401 — fixture


@pytest.fixture
def level(make_obj, make_scene, monkeypatch, tmp_path, fake_godot):
    hero, coin, ground = make_obj("Hero"), make_obj("Coin.001"), make_obj("Ground", dimensions=(40, 40, 0.2))
    spawn, lamp = make_obj("PlayerSpawn", "EMPTY"), make_obj("Lamp", "LIGHT")
    scene = make_scene([hero, coin, ground, spawn, lamp])
    monkeypatch.setattr(agent_api, "_scene", lambda: scene)
    monkeypatch.setattr(agent_api, "_godot_config", lambda: fake_godot)
    monkeypatch.setattr(exporter, "app_version", lambda: "9.9.9")
    written = []

    def fake_package(scene_arg, game_dir=""):
        spec, objects = exporter.current_spec(scene_arg)
        errors, warnings = exporter.game_spec.validate_spec(spec)
        game_dir = str(tmp_path / "games" / spec["slug"])
        result = {"ok": not errors, "game_dir": game_dir, "export_dir": os.path.join(game_dir, "mixar_export"),
                  "spec": spec, "errors": errors, "warnings": warnings, "export": None}
        if not errors:
            os.makedirs(result["export_dir"], exist_ok=True)
            with open(os.path.join(result["export_dir"], "game_spec.json"), "w") as handle:
                json.dump(spec, handle)
            written.append(game_dir)
        return result

    monkeypatch.setattr(exporter, "write_package", fake_package)
    import mixar.config.config as config
    monkeypatch.setattr(config, "get_community_api_url", lambda: "http://127.0.0.1:1")
    monkeypatch.setattr(config, "get_community_web_url", lambda: "http://store.test")
    scene.written = written
    return scene


def _wait(job_id, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = agent_api.game_job_status(job_id)
        if status["state"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("job did not settle")


def test_roles_configure_and_status_are_json_safe(level):
    reply = agent_api.set_game_roles([{"object": "Hero", "role": "player"},
                                      {"object": "Coin.001", "role": "collectible", "params": {"value": 3}},
                                      {"object": "Nope", "role": "goal"},
                                      {"object": "Lamp", "role": "static"}])
    assert [a["object"] for a in reply["applied"]] == ["Hero", "Coin.001"]
    assert {e["object"] for e in reply["errors"]} == {"Nope", "Lamp"} and reply["ok"] is False
    suggestions = agent_api.auto_assign_roles()
    assert {"object": "PlayerSpawn", "role": "spawn", "reason": "name"} in suggestions["assignments"]
    assert suggestions["applied"] is False and ROLE_PROP not in level.objects.get("PlayerSpawn")
    configured = agent_api.configure_game(title="Crystal Run", rules={"win": "collect_all", "lives": 5},
                                          camera={"distance": "far"})
    assert configured["spec"]["slug"] == "crystal-run" and configured["spec"]["rules"]["lives"] == 5
    assert configured["ok"] is False and configured["errors"]
    status = agent_api.game_status()
    json.dumps(status)
    assert set(status) == {"godot", "roles", "spec", "store", "last_build", "last_export", "last_publish"}
    assert status["roles"]["player"] == "Hero" and status["spec"]["valid"]
    assert set(status["godot"]) >= {"found", "path", "version"}


def test_publish_without_confirm_only_previews(level):
    agent_api.set_game_roles([{"object": "Hero", "role": "player"},
                              {"object": "Coin.001", "role": "collectible"}])
    reply = agent_api.start_game_publish(store_page={"tagline": "Grab gems"})
    assert reply["needs_confirmation"] is True and "job_id" not in reply
    assert reply["summary"]["action"] == "create" and reply["summary"]["platforms"] == ["web"]
    assert reply["summary"]["store_url"] == "http://store.test/games/untitled-game"
    assert level.written == [] and jobs.running() is None
    assert agent_api.start_game_publish(platforms=["ps5"], confirm=True)["error_code"] == "bad_request"


def test_invalid_spec_refuses_without_a_job(level):
    reply = agent_api.start_game_build()
    assert reply["error_code"] == "invalid_spec" and reply["job_id"] is None
    assert jobs.running() is None


def test_build_then_export_jobs_run_the_fork(level, monkeypatch):
    agent_api.set_game_roles([{"object": "Hero", "role": "player"},
                              {"object": "Coin.001", "role": "collectible"}])
    started = agent_api.start_game_build()
    assert started["state"] == "running" and len(started["job_id"]) == 32
    status = _wait(started["job_id"])
    assert status["state"] == "done", status
    assert status["kind"] == "build" and status["pct"] == 100.0
    assert status["result"]["stats"]["nodes"] == 3 and "fake warning" in status["result"]["warnings"]
    exported = _wait(agent_api.start_game_export(platforms=["web"])["job_id"])
    artifact = exported["result"]["artifacts"][0]
    assert artifact["platform"] == "web" and artifact["artifact"].endswith("game-web.zip")
    assert agent_api.game_status()["last_export"]["state"] == "done"
    assert agent_api.game_job_status("missing")["error_code"] == "unknown_job"


def test_fork_failure_carries_error_code(level, monkeypatch):
    agent_api.set_game_roles([{"object": "Hero", "role": "player"},
                              {"object": "Coin.001", "role": "collectible"}])
    monkeypatch.setenv("FAKE_FAIL_CODE", "2")
    status = _wait(agent_api.start_game_build()["job_id"])
    assert status["state"] == "failed" and status["error_code"] == "bad_spec"


def test_publish_job_uploads_and_remembers_the_game(level, stub, monkeypatch):  # noqa: F811
    agent_api.set_game_roles([{"object": "Hero", "role": "player"},
                              {"object": "Coin.001", "role": "collectible"}])
    agent_api.configure_game(title="Crystal Run")
    import mixar.config.config as config
    monkeypatch.setattr(config, "get_community_api_url", lambda: stub.base)
    from mixar.modules.game_studio.core import store_client
    monkeypatch.setattr(store_client, "_default_token", lambda: "tok")
    stub.routes.update({
        ("POST", "/api/v1/games"): (201, _envelope({"game": {"id": "g9", "slug": "crystal-run"}})),
        ("POST", "/api/v1/games/g9/builds"): (200, _envelope({"build_id": "b1", "put_url": stub.base + "/up/b1",
                                                              "headers": {}})),
        ("PUT", "/up/b1"): (200, {}),
        ("POST", "/api/v1/games/g9/builds/b1/complete"): (200, _envelope({"build": {"review_status": "pending"}})),
        ("POST", "/api/v1/games/g9/publish"): (200, _envelope({"game": {"id": "g9"}})),
        ("GET", "/api/v1/games/g9"): (200, _envelope({"game": {"id": "g9", "review_status": "pending"}})),
    })
    bpy = sys.modules["bpy"]
    monkeypatch.setattr(bpy.data.scenes, "get", lambda name: level)
    reply = agent_api.start_game_publish(store_page={"tagline": "Grab gems", "genres": ["Platformer"]},
                                         confirm=True)
    status = _wait(reply["job_id"])
    assert status["state"] == "done", status
    assert status["result"] == {"game_id": "g9", "store_url": "http://store.test/games/crystal-run",
                                "review_status": "pending", "builds": status["result"]["builds"]}
    assert status["result"]["builds"][0]["platform"] == "web"
    create = json.loads(stub.calls[0]["raw"])
    assert create["tagline"] == "Grab gems" and create["genres"] == ["platformer"]
    assert create["title"] == "Crystal Run" and create["source"] == "mixar"
    assert json.loads(level[STORE_PROP])["game_id"] == "g9"  # drained on the next agent call
    preview = agent_api.start_game_publish()
    assert preview["summary"]["action"] == "update"


def test_busy_refuses_a_second_job(level, monkeypatch):
    agent_api.set_game_roles([{"object": "Hero", "role": "player"},
                              {"object": "Coin.001", "role": "collectible"}])
    monkeypatch.setenv("FAKE_SLEEP", "5")
    first = agent_api.start_game_build()
    second = agent_api.start_game_export()
    assert second["error_code"] == "busy" and second["job_id"] == first["job_id"]
    assert agent_api.cancel_game_job(first["job_id"])["ok"]
    assert _wait(first["job_id"])["error_code"] == "cancelled"


def test_redact_hides_home():
    home = os.path.expanduser("~")
    assert agent_api._redact({"p": os.path.join(home, "x"), "n": [1, None, True]}) == \
        {"p": "~" + os.sep + "x", "n": [1, None, True]}

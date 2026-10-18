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
    assert {"object": "PlayerSpawn", "role": "spawn", "reason": "name", "parts": 0} in suggestions["assignments"]
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
    assert reply["summary"]["action"] == "create" and reply["summary"]["platforms"] == ["web", "macos", "windows"]
    assert reply["summary"]["store_url"] is None  # never composed client-side
    assert reply["summary"]["files"] == ["scene.glb", "untitled-game-web.zip", "untitled-game-macos.zip",
                                         "untitled-game-windows.zip"]
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


def _fake_ui_app(monkeypatch, scene):
    """A non-background app whose context scene is ``scene`` (a plain fake,
    so another suite's swapped ``bpy`` mock can't leak in)."""
    from types import SimpleNamespace as NS
    from mixar.modules.game_studio.core import launch
    fake = NS(app=NS(background=False), context=NS(scene=scene),
              data=NS(scenes=NS(get=lambda name: scene)))
    monkeypatch.setitem(sys.modules, "bpy", fake)
    monkeypatch.setattr(agent_api, "bpy", fake)
    monkeypatch.setattr(launch, "bpy", fake)


def _approve_like_the_ui(request_id):
    """What the approval operator does after the user's click."""
    from mixar.modules.game_studio.core import approvals, launch
    token = approvals._issue_token(request_id)
    payload = approvals._claim(request_id, token)
    assert payload is not None
    return launch.start_approved_publish(request_id, payload)


def test_publish_waits_for_the_user_then_uploads(level, stub, monkeypatch):  # noqa: F811
    agent_api.set_game_roles([{"object": "Hero", "role": "player"},
                              {"object": "Coin.001", "role": "collectible"}])
    agent_api.configure_game(title="Crystal Run")
    import mixar.config.config as config
    monkeypatch.setattr(config, "get_community_api_url", lambda: stub.base)
    from mixar.modules.game_studio.core import store_client
    monkeypatch.setattr(store_client, "_default_token", lambda: "tok")
    stub.routes.update({
        ("POST", "/api/v1/games"): (201, _envelope({"game": {"game_id": "g9", "slug": "crystal-run"}})),
        ("POST", "/api/v1/games/g9/builds"): (201, _envelope({"build_id": "b1", "put_url": stub.base + "/up/b1",
                                                              "method": "PUT", "headers": {}})),
        ("PUT", "/up/b1"): (200, {}),
        ("POST", "/api/v1/games/g9/builds/b1/complete"): (200, _envelope({"build": {"review_status": "pending"}})),
        ("POST", "/api/v1/games/g9/publish"): (200, _envelope({
            "game_id": "g9", "slug": "crystal-run", "store_url": "http://store.test/games/crystal-run",
            "review_status": "pending", "builds": [{"build_id": "b1", "review_status": "pending"}]})),
    })
    _fake_ui_app(monkeypatch, level)
    monkeypatch.setattr(agent_api, "_ask_user", lambda *a: None)
    reply = agent_api.start_game_publish(store_page={"tagline": "Grab gems", "genres": ["Platformer"]},
                                         confirm=True)
    assert reply["state"] == "awaiting_user_approval" and reply["job_id"] == reply["request_id"]
    waiting = agent_api.game_job_status(reply["request_id"])
    assert waiting["state"] == "awaiting_user_approval" and not stub.calls
    started = _approve_like_the_ui(reply["request_id"])
    assert started["ok"] and started["job_id"] == reply["request_id"]
    status = _wait(reply["request_id"])
    assert status["state"] == "done", status
    assert {k: status["result"][k] for k in ("game_id", "store_url", "review_status")} == {
        "game_id": "g9", "store_url": "http://store.test/games/crystal-run", "review_status": "pending"}
    # The fake fork advertises no "capture": published without store art, said so.
    assert "cannot render store images" in status["result"]["warnings"][0]
    assert [b["platform"] for b in status["result"]["builds"]] == ["web", "macos", "windows"]
    declared = [json.loads(c["raw"]) for c in stub.calls if c["path"] == "/api/v1/games/g9/builds"]
    assert [(d["platform"], d.get("launch"), d.get("signing")) for d in declared] == [
        ("web", None, None), ("macos", "Crystal Run.app", "adhoc"),
        ("windows", "Crystal Run.exe", "unsigned")]
    assert len({d["filename"] for d in declared}) == 3  # one zip per platform
    create = json.loads(stub.calls[0]["raw"])
    assert create["tagline"] == "Grab gems" and create["genres"] == ["platformer"]
    assert create["title"] == "Crystal Run" and create["source"] == "mixar"
    assert json.loads(level[STORE_PROP])["store_url"] == "http://store.test/games/crystal-run"
    preview = agent_api.start_game_publish()
    assert preview["summary"]["action"] == "update"
    assert preview["summary"]["store_url"] == "http://store.test/games/crystal-run"


def test_profile_required_points_at_the_profile_page(level, stub, monkeypatch):  # noqa: F811
    agent_api.set_game_roles([{"object": "Hero", "role": "player"},
                              {"object": "Coin.001", "role": "collectible"}])
    import mixar.config.config as config
    monkeypatch.setattr(config, "get_community_api_url", lambda: stub.base)
    from mixar.modules.game_studio.core import store_client
    monkeypatch.setattr(store_client, "_default_token", lambda: "tok")
    stub.routes[("POST", "/api/v1/games")] = (409, {"detail": {
        "code": "profile_required", "message": "Pick a community handle first"}})
    _fake_ui_app(monkeypatch, level)
    monkeypatch.setattr(agent_api, "_ask_user", lambda *a: None)
    request_id = agent_api.start_game_publish(confirm=True)["request_id"]
    _approve_like_the_ui(request_id)
    status = _wait(request_id)
    assert status["error_code"] == "profile_required"
    assert "http://store.test/settings/profile" in status["error"]


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
    assert agent_api._redact("Exported " + os.path.join(home, "g.zip")) == "Exported ~" + os.sep + "g.zip"


def test_settled_jobs_replace_the_last_progress_line():
    jobs.reset_for_tests()
    done = jobs.create("build")
    jobs.update(done, pct=90, message="Scanning and importing project assets")
    jobs.finish(done, result={})
    failed = jobs.create("export")
    jobs.update(failed, message="Exporting web")
    jobs.finish(failed, error="templates missing", error_code="templates_missing")
    assert jobs.get(done)["message"] == "Done."
    assert jobs.get(failed)["message"] == "templates missing"
    from mixar.modules.game_studio.constants import platform_list
    assert platform_list(["web", "macos", "windows", "linux"]) == "Web, macOS, Windows, Linux"


def _capture_ctx(tmp_path, fake_godot):
    from mixar.modules.game_studio.core import godot_locator
    project = tmp_path / "game" / "project"
    project.mkdir(parents=True)
    return {"game_dir": str(tmp_path / "game")}, godot_locator.validate(fake_godot)


class _Handle:
    import threading
    cancel_event = threading.Event()

    def progress(self, *args, **kwargs):
        pass


def test_capture_renders_store_art_with_the_fork(tmp_path, fake_godot, monkeypatch):
    monkeypatch.setenv("FAKE_CAPS", "capture")
    ctx, verdict = _capture_ctx(tmp_path, fake_godot)
    assert verdict["capabilities"] == ["capture"]
    images, warnings = pipeline.capture_stage(ctx, _Handle(), verdict)
    assert [kind for kind, _ in images] == ["capsule", "screenshot"] and warnings == []
    with open(images[0][1], "rb") as handle:
        assert handle.read() == b"\x89PNG1280x720"


def test_capture_skipped_without_the_capability_and_failures_warn(tmp_path, fake_godot, monkeypatch):
    calls = []
    real_run = pipeline.godot_runner.run
    monkeypatch.setattr(pipeline.godot_runner, "run", lambda *a, **k: calls.append(a) or real_run(*a, **k))
    ctx, verdict = _capture_ctx(tmp_path, fake_godot)
    images, warnings = pipeline.capture_stage(ctx, _Handle(), verdict)
    assert images == [] and not calls and "cannot render" in warnings[0]  # never an unknown flag
    monkeypatch.setenv("FAKE_CAPTURE_FAIL", "1")
    images, warnings = pipeline.capture_stage(ctx, _Handle(), dict(verdict, capabilities=["capture"]))
    assert images == [] and len(warnings) == 2 and "capture_failed" in warnings[0]


def test_publish_never_grabs_the_mixar_window():
    from pathlib import Path
    root = Path(__file__).parents[2] / "src/scripts/mixar/modules/game_studio"
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "screenshot_area" not in source and "screen.screenshot" not in source, path


def test_missing_windows_templates_skip_windows_with_a_warning(level, monkeypatch):
    agent_api.set_game_roles([{"object": "Hero", "role": "player"},
                              {"object": "Coin.001", "role": "collectible"}])
    monkeypatch.setenv("FAKE_TEMPLATES_MISSING", "windows")
    status = _wait(agent_api.start_game_export()["job_id"])  # default: web + macOS + Windows
    assert status["state"] == "done", status
    assert [a["platform"] for a in status["result"]["artifacts"]] == ["web", "macos"]
    assert "Windows build skipped: export templates not installed." in status["result"]["warnings"]
    monkeypatch.setenv("FAKE_TEMPLATES_MISSING", "web,windows")
    status = _wait(agent_api.start_game_export(platforms=["windows"])["job_id"])  # nothing else: fail
    assert status["state"] == "failed" and status["error_code"] == "templates_missing"

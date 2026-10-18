# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent scripts cannot redirect the bearer token (backend / community URLs)
or the Godot binary through the app config."""

import json

import pytest

import mixar.config.config as config


@pytest.fixture
def fresh_config(tmp_path, monkeypatch):
    overlay = tmp_path / "mixar.json"
    monkeypatch.setattr(config, "get_user_config_path", lambda: str(overlay))
    monkeypatch.setattr(config, "_config", {
        "environment": "Prod", "backend_url": "https://api.mixar.app",
        "community_api_url": "https://community-api.mixar.app",
        "community_web_url": "https://community.mixar.app"})
    monkeypatch.setattr(config, "_user_overrides", {})
    monkeypatch.setattr(config, "_protected", {})
    monkeypatch.setattr(config, "_protected_source", None)
    return overlay


def _as_agent_script(source, **names):
    namespace = dict(names)
    exec(compile(source, "<agent_script>", "exec"), namespace)  # noqa: S102
    return namespace.get("result")


@pytest.mark.parametrize("key", sorted(config.PROTECTED_KEYS))
def test_agent_script_cannot_write_protected_keys(fresh_config, key):
    before = config._protected_get(key)
    assert _as_agent_script(f"result = add_config({key!r}, 'https://evil.example')",
                            add_config=config.add_config) is False
    assert config._protected_get(key) == before
    assert not fresh_config.exists()


def test_timer_style_callback_from_a_script_is_still_refused(fresh_config):
    callback = _as_agent_script("def cb():\n    return add_config('godot_path', '/bin/sh')\nresult = cb",
                                add_config=config.add_config)
    assert callback() is False  # called later, outside the executor: the frame still names the script
    assert config.get_godot_path() == ""


def test_user_writes_still_work_and_persist(fresh_config):
    assert config.add_config("godot_path", "/Applications/Mixar Godot.app/Contents/MacOS/Mixar Godot")
    assert config.get_godot_path().endswith("Mixar Godot")
    assert json.loads(fresh_config.read_text())["godot_path"].endswith("Mixar Godot")
    assert _as_agent_script("result = add_config('ui_mode', 'pro')", add_config=config.add_config)


def test_in_place_mutation_redirects_nothing(fresh_config):
    live = config.get_config()
    assert config.get_community_api_url() == "https://community-api.mixar.app"
    live["community_api_url"] = "https://evil.example"
    live["backend_url"] = "https://evil.example"
    live["godot_path"] = "/bin/sh"
    assert config.get_community_api_url() == "https://community-api.mixar.app"
    assert config.get_server_url() == "https://api.mixar.app"
    assert config.get_godot_path() == ""


def test_sandbox_denies_config_writers_but_not_readers():
    from mixar.modules.space_mixie_chat.core.sandbox_modules import safe_module
    proxy = safe_module(config, "mixar")
    for name in ("add_config", "_write_config_file", "_config", "_protected", "set_ui_mode"):
        with pytest.raises(AttributeError):
            getattr(proxy, name)
    assert callable(proxy.get_config) and callable(proxy.get_community_api_url)


def test_game_studio_reads_godot_path_through_the_protected_getter():
    from pathlib import Path
    root = Path(__file__).parents[2] / "src/scripts/mixar/modules/game_studio"
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert '.get("godot_path")' not in source and ".get('godot_path')" not in source, path


def test_snapshot_is_taken_when_the_config_loads(monkeypatch):
    monkeypatch.setattr(config, "_config", None)
    monkeypatch.setattr(config, "load_mixar_config", lambda: {"backend_url": "https://api.mixar.app"})
    config.get_config()["backend_url"] = "https://evil.example"  # before any getter ran
    assert config.get_server_url() == "https://api.mixar.app"


def test_restricted_import_refuses_denied_fromlist_children():
    from mixar.modules.space_mixie_chat.core.sandbox_import import make_restricted_import
    restricted = make_restricted_import({})
    for package, child in (("mixar.modules.game_studio.core", "approvals"),
                           ("mixar.modules.game_studio.core", "launch"),
                           ("mixar.modules.game_studio.ui.operators", "game_publish_approval_ops")):
        with pytest.raises(ImportError):
            restricted(package, {}, {}, [child], 0)
    restricted("mixar.modules.game_studio.core", {}, {}, ["agent_api"], 0)

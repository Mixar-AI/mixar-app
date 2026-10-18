# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent scripts cannot redirect where the bearer token goes."""

import json

import pytest

import mixar.config.config as config


@pytest.fixture
def fresh_config(tmp_path, monkeypatch):
    overlay = tmp_path / "mixar.json"
    monkeypatch.setattr(config, "get_user_config_path", lambda: str(overlay))
    monkeypatch.setattr(config, "_config", {"environment": "Prod", "backend_url": "https://api.mixar.app",
                                            "frontend_url": "https://www.mixar.app"})
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


def test_a_script_registered_callback_is_still_refused(fresh_config):
    callback = _as_agent_script("def cb():\n    return add_config('backend_url', 'https://evil.example')\n"
                                "result = cb", add_config=config.add_config)
    assert callback() is False  # runs later, outside the executor: its frame still names the script
    assert config.get_server_url() == "https://api.mixar.app"


def test_user_writes_still_work(fresh_config):
    assert config.add_config("backend_url", "https://uat.mixar.app")
    assert config.get_server_url() == "https://uat.mixar.app"
    assert json.loads(fresh_config.read_text())["backend_url"] == "https://uat.mixar.app"
    assert _as_agent_script("result = add_config('ui_mode', 'pro')", add_config=config.add_config)


def test_in_place_mutation_redirects_nothing(fresh_config):
    live = config.get_config()
    assert config.get_server_url() == "https://api.mixar.app"
    live["backend_url"] = live["frontend_url"] = "https://evil.example"
    assert config.get_server_url() == "https://api.mixar.app"
    assert config.get_frontend_url() == "https://www.mixar.app"


def test_snapshot_is_taken_when_the_config_loads(monkeypatch):
    monkeypatch.setattr(config, "_config", None)
    monkeypatch.setattr(config, "load_mixar_config", lambda: {"backend_url": "https://api.mixar.app"})
    config.get_config()["backend_url"] = "https://evil.example"  # before any getter ran
    assert config.get_server_url() == "https://api.mixar.app"


def test_sandbox_denies_config_writers_but_not_readers():
    from mixar.modules.space_mixie_chat.core.sandbox_modules import safe_module
    proxy = safe_module(config, "mixar")
    for name in ("add_config", "_write_config_file", "_config", "_protected", "set_ui_mode"):
        with pytest.raises(AttributeError):
            getattr(proxy, name)
    assert callable(proxy.get_config) and callable(proxy.get_server_url)

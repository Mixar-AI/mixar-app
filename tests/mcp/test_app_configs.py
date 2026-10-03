# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The Connect dialog shows each app's exact setup and adds Mixar to Claude Code
and Codex in one click, without disturbing anything else in their configs."""

import json
from pathlib import Path
import shlex
import sys
import tomllib

import pytest

from mixar.modules.mcp_bridge.core import app_configs
from mixar.modules.mcp_bridge.core.setup import render

LAUNCHER = "/Users/me/.mixar/connector/mixar-mcp"


def test_every_app_renders_the_same_launcher_in_its_format(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    out = {key: render(key, LAUNCHER, []) for key, _name, _how in app_configs.APPS}
    assert shlex.split(out["CLAUDE_CODE"]) == ["claude", "mcp", "add", "--scope", "user", "mixar", "--", LAUNCHER]
    assert tomllib.loads(out["CODEX"])["mcp_servers"]["mixar"] == {
        "command": LAUNCHER, "args": [], "tool_timeout_sec": 610}
    assert json.loads(out["CLAUDE_DESKTOP"]) == json.loads(out["JSON"]) == {
        "mcpServers": {"mixar": {"command": LAUNCHER, "args": []}}}
    assert json.loads(out["CURSOR"])["mcpServers"]["mixar"]["type"] == "stdio"
    assert json.loads(out["VSCODE"])["servers"]["mixar"]["command"] == LAUNCHER
    opencode = json.loads(out["OPENCODE"])["mcp"]["mixar"]
    assert opencode["command"] == [LAUNCHER] and opencode["timeout"] >= 30_000
    assert out["COMMAND"] == LAUNCHER


def test_config_files_are_where_each_app_reads_them(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(app_configs, "_home", lambda: tmp_path)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    assert app_configs.config_path("CURSOR") == tmp_path / ".cursor" / "mcp.json"
    assert app_configs.config_path("CODEX") == tmp_path / ".codex" / "config.toml"
    assert app_configs.config_path("CLAUDE_DESKTOP").parts[-3:] == ("Application Support", "Claude",
                                                                   "claude_desktop_config.json")
    assert app_configs.config_path("JSON") is None and app_configs.config_path("CLAUDE_CODE") is None


# ---------------------------------------------------------------------- Codex

EXISTING = '''# my settings
model = "gpt-6"

[mcp_servers.other]
command = "other-server"

[projects."/Users/me/work"]
trust_level = "trusted"
'''


@pytest.fixture
def codex(tmp_path):
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir()
    return path


def test_codex_gets_mixar_appended_and_keeps_everything_else(codex):
    codex.write_text(EXISTING)
    assert app_configs.add_to_codex(LAUNCHER, [], codex) == ("added", "")
    text = codex.read_text()
    assert text.startswith(EXISTING.rstrip("\n")) and "# my settings" in text
    data = tomllib.loads(text)
    assert data["mcp_servers"]["mixar"]["tool_timeout_sec"] == 610
    assert data["mcp_servers"]["other"] == {"command": "other-server"}
    assert codex.with_name("config.toml.mixar-backup").read_text() == EXISTING


def test_codex_already_set_up_is_left_alone(codex):
    codex.write_text(EXISTING + "\n" + render("CODEX", LAUNCHER, []))
    before = codex.read_text()
    assert app_configs.add_to_codex(LAUNCHER, [], codex) == ("already", "")
    assert codex.read_text() == before


def test_codex_stale_entry_is_replaced_with_its_sub_tables(codex):
    codex.write_text(EXISTING + '\n[mcp_servers.mixar]\ncommand = "/old/mixar-mcp"\n\n'
                     '[mcp_servers.mixar.env]\nX = "1"\n\n[tui]\ntheme = "dark"\n')
    assert app_configs.add_to_codex(LAUNCHER, [], codex) == ("updated", "")
    data = tomllib.loads(codex.read_text())
    assert data["mcp_servers"]["mixar"] == {"command": LAUNCHER, "args": [], "tool_timeout_sec": 610}
    assert data["tui"] == {"theme": "dark"} and data["mcp_servers"]["other"]


def test_codex_is_never_rewritten_when_it_cannot_be_read_or_updated(codex):
    codex.write_text("model = [broken\n")
    status, _ = app_configs.add_to_codex(LAUNCHER, [], codex)
    assert status == "failed" and codex.read_text() == "model = [broken\n"
    inline = 'mcp_servers = { mixar = { command = "/old" } }\n'
    codex.write_text(inline)
    status, _ = app_configs.add_to_codex(LAUNCHER, [], codex)
    assert status == "failed" and codex.read_text() == inline


def test_codex_without_its_settings_folder_is_not_created(tmp_path):
    status, detail = app_configs.add_to_codex(LAUNCHER, [], tmp_path / "missing" / "config.toml")
    assert status == "failed" and "open Codex once" in detail


# ---------------------------------------------------------------- Claude Code

def fake_claude(monkeypatch, responses):
    calls = []

    def run(args):
        calls.append(args[1:3] if args[1] == "mcp" else args)
        return responses.pop(0)

    monkeypatch.setattr(app_configs, "_run", run)
    return calls


def test_claude_code_is_added_through_its_own_command(monkeypatch):
    calls = fake_claude(monkeypatch, [(0, "Added stdio MCP server mixar")])
    assert app_configs.add_to_claude_code(LAUNCHER, [], cli="/bin/claude") == ("added", "")
    assert calls == [["mcp", "add"]]


def test_claude_code_existing_entry_is_kept_or_replaced(monkeypatch):
    fake_claude(monkeypatch, [(1, "MCP server mixar already exists in user config"),
                              (0, "mixar:\n  Scope: User config\n  Command: " + LAUNCHER)])
    assert app_configs.add_to_claude_code(LAUNCHER, [], cli="/bin/claude") == ("already", "")
    calls = fake_claude(monkeypatch, [(1, "already exists"), (0, "Command: /old/path"), (0, "Removed"), (0, "Added")])
    assert app_configs.add_to_claude_code(LAUNCHER, [], cli="/bin/claude") == ("updated", "")
    assert calls == [["mcp", "add"], ["mcp", "get"], ["mcp", "remove"], ["mcp", "add"]]


def test_claude_code_missing_cli_points_to_the_copy_button(monkeypatch):
    monkeypatch.setattr(app_configs, "find_cli", lambda name: None)
    status, detail = app_configs.add_to_claude_code(LAUNCHER, [])
    assert status == "failed" and "Copy the command" in detail


def test_the_dialog_offers_add_copy_open_and_the_guide():
    dialog = (Path(__file__).parents[2] / "src/scripts/mixar/modules/mcp_bridge/ui/operators/connect.py").read_text()
    for text in ('"mixar.mcp_add_to_app"', 'text="Copy"', 'text="Open Config File"',
                 'text="Copy MCP Config"', 'text="Setup Guide"', "translation_context=PRODUCT_NAMES"):
        assert text in dialog
    assert app_configs.ADDABLE == ("CLAUDE_CODE", "CODEX")

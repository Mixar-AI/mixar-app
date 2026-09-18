# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Functional tests for the Project Rules mutation API (core/rules_api.py).

rules_api is the single mutation surface shared by the UI operators and
the agent's PROJECT_RULES tools — these tests exercise it directly with a
FakeScene (project store) and a tmp_path-backed global store, outside
Blender.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import pytest

from mixar.modules.space_mixie_chat.core import rules_api, rules_global
from mixar.modules.space_mixie_chat.core.rules import (
    get_project_rules,
    parse_rules,
)


class FakeScene:
    """Minimal stand-in for bpy.types.Scene with the rules property."""

    def __init__(self):
        self.name = "Scene"
        self.mixie_chat_rules = ""


@pytest.fixture(autouse=True)
def _tmp_global_store(tmp_path, monkeypatch):
    """Point the global rules store at a per-test temp file."""
    path = tmp_path / "global_rules.json"
    monkeypatch.setattr(rules_global, "_store_path", lambda: str(path))
    yield path


@pytest.fixture()
def scene():
    return FakeScene()


# ---------------------------------------------------------------------------
# Add + unified listing
# ---------------------------------------------------------------------------

def test_add_project_rule_persists_and_lists(scene):
    result = rules_api.add_rule(scene, "  keep everything low-poly  ")
    assert result["success"]
    assert result["rules"] == [
        {"index": 0, "text": "keep everything low-poly", "enabled": True,
         "scope": "project"},
    ]
    # Persisted as the JSON store format.
    assert parse_rules(scene.mixie_chat_rules) == [
        {"text": "keep everything low-poly", "enabled": True},
    ]


def test_add_global_rule_hits_disk_and_orders_first(scene, _tmp_global_store):
    rules_api.add_rule(scene, "project rule")
    result = rules_api.add_rule(scene, "always answer in Spanish", scope="global")
    assert result["success"]
    assert _tmp_global_store.is_file()
    scopes = [(r["scope"], r["text"]) for r in result["rules"]]
    # Unified index contract: globals first, then this file's rules.
    assert scopes == [
        ("global", "always answer in Spanish"),
        ("project", "project rule"),
    ]
    assert [r["index"] for r in result["rules"]] == [0, 1]


def test_add_rejects_empty_text_and_bad_scope(scene):
    assert not rules_api.add_rule(scene, "   ")["success"]
    result = rules_api.add_rule(scene, "x", scope="universe")
    assert not result["success"]
    assert "scope" in result["error"]


# ---------------------------------------------------------------------------
# Update: text / enabled / scope
# ---------------------------------------------------------------------------

def test_update_text_and_enabled(scene):
    rules_api.add_rule(scene, "old wording")
    result = rules_api.update_rule(scene, 0, text="new wording")
    assert result["success"]
    assert result["rules"][0]["text"] == "new wording"

    result = rules_api.update_rule(scene, 0, enabled=False)
    assert result["success"]
    assert result["rules"][0]["enabled"] is False
    # Disabled rules drop out of the wire text.
    assert get_project_rules(scene) == ""


def test_update_requires_a_field_and_valid_index(scene):
    rules_api.add_rule(scene, "a rule")
    assert not rules_api.update_rule(scene, 0)["success"]
    result = rules_api.update_rule(scene, 5, text="x")
    assert not result["success"]
    # Error responses still carry the fresh list so callers can recover.
    assert len(result["rules"]) == 1


def test_scope_move_project_to_global_and_back(scene, _tmp_global_store):
    rules_api.add_rule(scene, "movable rule")
    result = rules_api.update_rule(scene, 0, scope="global")
    assert result["success"]
    assert result["rules"][0]["scope"] == "global"
    assert parse_rules(scene.mixie_chat_rules) == []
    assert rules_global.load_global_rules() == [
        {"text": "movable rule", "enabled": True},
    ]

    result = rules_api.update_rule(scene, 0, scope="project")
    assert result["success"]
    assert result["rules"][0]["scope"] == "project"
    assert rules_global.load_global_rules() == []


def test_scope_move_keeps_rule_when_destination_full(scene, monkeypatch):
    rules_api.add_rule(scene, "stays put")
    monkeypatch.setattr(rules_api, "save_global_rules", lambda rules: False)
    result = rules_api.update_rule(scene, 0, scope="global")
    assert not result["success"]
    # Destination write failed -> the rule must remain in the project store.
    assert result["rules"][0]["scope"] == "project"
    assert parse_rules(scene.mixie_chat_rules) == [
        {"text": "stays put", "enabled": True},
    ]


# ---------------------------------------------------------------------------
# Remove + caps
# ---------------------------------------------------------------------------

def test_remove_rule(scene):
    rules_api.add_rule(scene, "first")
    rules_api.add_rule(scene, "second")
    result = rules_api.remove_rule(scene, 0)
    assert result["success"]
    assert [r["text"] for r in result["rules"]] == ["second"]

    result = rules_api.remove_rule(scene, 7)
    assert not result["success"]


def test_store_cap_rejected_with_actionable_error(scene):
    rules_api.add_rule(scene, "x" * 9900)
    result = rules_api.add_rule(scene, "y" * 200)
    assert not result["success"]
    assert "full" in result["error"]
    assert len(result["rules"]) == 1


# ---------------------------------------------------------------------------
# Agent dispatcher + wire integration
# ---------------------------------------------------------------------------

def test_run_agent_tool_dispatch(scene):
    listed = rules_api.run_agent_tool(scene, "list_rules", {})
    assert listed == {"success": True, "rules": [], "count": 0}

    added = rules_api.run_agent_tool(
        scene, "add_rule", {"text": "always answer in Spanish", "scope": "global"})
    assert added["success"]

    updated = rules_api.run_agent_tool(
        scene, "update_rule", {"index": 0, "enabled": False})
    assert updated["success"]
    assert updated["rules"][0]["enabled"] is False

    removed = rules_api.run_agent_tool(scene, "remove_rule", {"index": 0})
    assert removed["success"]
    assert removed["rules"] == []

    unknown = rules_api.run_agent_tool(scene, "explode_rules", {})
    assert not unknown["success"]
    assert "unknown" in unknown["error"]


def test_agent_added_rules_reach_the_wire_text(scene):
    rules_api.run_agent_tool(
        scene, "add_rule", {"text": "always answer in Spanish", "scope": "global"})
    rules_api.run_agent_tool(scene, "add_rule", {"text": "keep it low-poly"})
    # compose_wire_message / the mid-session fingerprint both hash this text.
    assert get_project_rules(scene) == (
        "always answer in Spanish\n\nkeep it low-poly"
    )

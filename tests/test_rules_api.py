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
    rules_snapshot,
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
        {"id": result["rules"][0]["id"], "index": 0, "text": "keep everything low-poly", "enabled": True,
         "scope": "project"},
    ]
    # Persisted as the JSON store format.
    assert parse_rules(scene.mixie_chat_rules) == [
        {"id": result["rules"][0]["id"], "text": "keep everything low-poly", "enabled": True},
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
        {"id": result["rules"][0]["id"], "text": "movable rule", "enabled": True},
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
        {"id": result["rules"][0]["id"], "text": "stays put", "enabled": True},
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
    assert listed == {"success": True, "rules": [], "count": 0,
                      "rules_snapshot": {"version": 1, "global": [], "project": []}}

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



def test_legacy_ids_survive_unrelated_deletion_and_are_scope_specific(scene):
    import json
    raw = json.dumps([{"text": "unrelated"}, {"text": "keep"}, {"text": "keep"}])
    scene.mixie_chat_rules = raw
    before = rules_api.list_unified(scene)
    assert len({r["id"] for r in before}) == 3
    assert rules_snapshot(scene) == rules_snapshot(scene)
    assert scene.mixie_chat_rules == raw, "Reads must not mutate saved files"
    assert parse_rules(raw, scope="global")[1]["id"] != before[1]["id"]
    assert parse_rules('[{"text":"keep"}]')[0]["id"] == before[1]["id"]
    assert rules_api.remove_rule(scene, rule_id=before[0]["id"])["success"]
    assert [r["id"] for r in rules_api.list_unified(scene)] == [r["id"] for r in before[1:]]
    assert all("id" in r for r in json.loads(scene.mixie_chat_rules))


def test_id_mutation_survives_index_shift_and_scope_move(scene):
    first = rules_api.add_rule(scene, "first")["rules"][0]["id"]
    target = rules_api.add_rule(scene, "target")["rules"][1]["id"]
    rules_api.add_rule(scene, "global", scope="global")
    assert rules_api.run_agent_tool(scene, "update_rule", {
        "rule_id": target, "text": "edited", "scope": "global"})["success"]
    rows = rules_api.list_unified(scene)
    assert next(r for r in rows if r["id"] == target)["text"] == "edited"
    assert next(r for r in rows if r["id"] == first)["text"] == "first"
    assert rules_api.run_agent_tool(scene, "remove_rule", {"rule_id": target})["success"]
    assert not rules_api.remove_rule(scene, 0, rule_id=target)["success"]


def test_failed_remove_reports_failure_and_retains_rule(scene, monkeypatch):
    rule = rules_api.add_rule(scene, "global", scope="global")["rules"][0]
    monkeypatch.setattr(rules_api, "save_global_rules", lambda _: False)
    result = rules_api.remove_rule(scene, rule_id=rule["id"])
    assert not result["success"]
    assert result["rules"] == [rule]


def test_failed_source_save_rolls_back_scope_move(scene, monkeypatch):
    rule = rules_api.add_rule(scene, "global", scope="global")["rules"][0]
    monkeypatch.setattr(rules_api, "save_global_rules", lambda _: False)
    result = rules_api.update_rule(scene, rule_id=rule["id"], scope="project")
    assert not result["success"]
    assert result["rules"] == [rule]
    assert parse_rules(scene.mixie_chat_rules) == []


def test_failed_move_rollback_reports_duplicate(scene, monkeypatch):
    rule = rules_api.add_rule(scene, "global", scope="global")["rules"][0]
    monkeypatch.setattr(rules_api, "save_global_rules", lambda _: False)
    save = rules_api.write_project_rules
    monkeypatch.setattr(rules_api, "write_project_rules", lambda scn, rows: save(scn, rows) if rows else False)
    result = rules_api.update_rule(scene, rule_id=rule["id"], scope="project")
    assert not result["success"] and "duplicate" in result["error"]
    assert len(result["rules"]) == 2
    assert not rules_api.remove_rule(scene, rule_id=rule["id"])["success"]


def test_global_write_uses_unique_temp_and_cleans_failed_write(scene, monkeypatch, _tmp_global_store):
    old = rules_api.add_rule(scene, "saved", scope="global")["rules"]
    paths = []
    def fail_replace(src, dst):
        paths.append(src)
        raise OSError("read-only store")
    monkeypatch.setattr(rules_global.os, "replace", fail_replace)
    for _ in range(2):
        assert not rules_api.add_rule(scene, "new", scope="global")["success"]
    assert len(set(paths)) == 2
    assert all(not Path(path).exists() for path in paths)
    assert rules_api.list_unified(scene) == old


def test_snapshot_contains_disabled_rules_and_explicit_empty_scopes(scene):
    assert rules_snapshot(scene) == {"version": 1, "global": [], "project": []}
    rule = rules_api.add_rule(scene, "disabled")["rules"][0]
    result = rules_api.update_rule(scene, rule_id=rule["id"], enabled=False)
    assert result["rules_snapshot"]["project"] == [{"id": rule["id"], "text": "disabled", "enabled": False}]
    assert get_project_rules(scene) == ""



def test_rule_id_dispatch_ignores_optional_null_index(scene):
    rule = rules_api.add_rule(scene, "target")["rules"][0]
    result = rules_api.run_agent_tool(scene, "update_rule", {
        "rule_id": rule["id"], "index": None, "text": "changed"})
    assert result["success"]
    assert result["rules"][0]["text"] == "changed"
    assert not rules_api.run_agent_tool(scene, "remove_rule", {"index": None})["success"]



def test_project_source_failure_and_global_rollback_failure_are_honest(scene, monkeypatch):
    rule = rules_api.add_rule(scene, "project rule")["rules"][0]
    save = rules_api.save_global_rules
    monkeypatch.setattr(rules_api, "write_project_rules", lambda *_: False)
    monkeypatch.setattr(rules_api, "save_global_rules", lambda rows: save(rows) if rows else False)
    result = rules_api.update_rule(scene, rule_id=rule["id"], scope="global", text="edited")
    assert not result["success"]
    assert "original rule was kept" in result["error"]
    assert "duplicate may remain" in result["error"]
    assert result["rules_snapshot"]["project"][0]["text"] == "project rule"
    assert result["rules_snapshot"]["global"][0]["text"] == "edited"


@pytest.mark.parametrize("scope", ["project", "global"])
def test_full_legacy_store_migrates_and_remains_editable(scene, _tmp_global_store, scope):
    import json
    from mixar.modules.space_mixie_chat.core.rules import serialize_rules

    raw = json.dumps([{"text": f"{i:02d}" + "x" * 158, "enabled": True}
                      for i in range(50)], separators=(",", ":"))
    assert len(raw.encode()) == 9351
    if scope == "global":
        _tmp_global_store.write_text(raw)
    else:
        scene.mixie_chat_rules = raw
    before = rules_api.list_unified(scene)
    assert len(serialize_rules(before).encode()) > 9999
    removed = rules_api.remove_rule(scene, rule_id=before[0]["id"])
    assert removed["success"]
    assert [r["id"] for r in removed["rules"]] == [r["id"] for r in before[1:]]
    target = before[1]["id"]
    assert rules_api.update_rule(scene, rule_id=target, enabled=False)["success"]
    assert rules_api.update_rule(scene, rule_id=target, text="shortened")["success"]
    assert rules_api.add_rule(scene, "new rule", scope=scope)["success"]
    saved = rules_api.list_unified(scene)
    assert next(r for r in saved if r["id"] == target)["text"] == "shortened"
    assert next(r for r in saved if r["id"] == target)["enabled"] is False
    assert all(r["scope"] == scope for r in saved)


@pytest.mark.parametrize("scope", ["project", "global"])
def test_store_budget_counts_utf8_text_and_metadata_separately(scene, scope):
    assert rules_api.add_rule(scene, "界" * 3333, scope=scope)["success"]
    before = rules_api.list_unified(scene)
    assert not rules_api.add_rule(scene, "x", scope=scope)["success"]
    assert rules_api.list_unified(scene) == before
    assert rules_api.update_rule(scene, rule_id=before[0]["id"], enabled=False)["success"]


def test_store_entry_and_serialized_bounds():
    from mixar.modules.space_mixie_chat.core.rules import rules_fit_store, serialize_rules
    rows = [{"id": str(i), "text": "x", "enabled": True} for i in range(512)]
    assert rules_fit_store(rows, serialize_rules(rows))
    rows.append({"id": "extra", "text": "x", "enabled": True})
    assert not rules_fit_store(rows, serialize_rules(rows))
    assert not rules_fit_store(rows[:1], "x" * 65537)

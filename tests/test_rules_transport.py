# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Every chat/input surface carries the latest scoped rules at the wire boundary."""
import sys
from types import SimpleNamespace

import pytest
from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.core import rules_api, rules_global, session, turn_transport


@pytest.fixture
def transport(monkeypatch, tmp_path):
    scene = SimpleNamespace(name="RulesScene", mixie_chat_rules="", mixie_chat_messages=[])
    monkeypatch.setattr(sys.modules["bpy"].data, "scenes", {scene.name: scene})
    monkeypatch.setattr(rules_global, "_store_path", lambda: str(tmp_path / "global.json"))
    monkeypatch.setattr(session, "get_session_manager", lambda: SimpleNamespace(get_state=lambda _: SessionState.IDLE))
    monkeypatch.setattr(turn_transport.turn_events, "expect", lambda *args: None)
    monkeypatch.setattr(turn_transport, "collect_user_preferences", lambda: {})
    calls = []
    monkeypatch.setattr(turn_transport, "command", lambda method, payload, *a, **kw: calls.append((method, payload)))
    return scene, turn_transport.TurnTransport(scene.name), calls


def test_all_sends_refresh_snapshot_including_disabled_and_cleared_rules(transport):
    scene, handler, calls = transport
    assert handler.start_stream("hello", "instance", "session")
    assert calls[-1][1]["rules"] == {"version": 1, "global": [], "project": []}
    rule = rules_api.add_rule(scene, "Use metric units")["rules"][0]
    for action in ("respond", "modify"):
        assert handler.start_input_stream("session", action, text="yes")
        assert calls[-1][0] == "input"
        assert calls[-1][1]["text"] == "yes"
        assert calls[-1][1]["rules"]["project"][0]["id"] == rule["id"]
    rules_api.update_rule(scene, rule_id=rule["id"], enabled=False)
    assert handler.start_stream("continue", "instance", "session", interjecting=True)
    assert calls[-1][1]["rules"]["project"][0]["enabled"] is False
    rules_api.remove_rule(scene, rule_id=rule["id"])
    assert handler.start_input_stream("session", "respond", answers={"choice": "yes"})
    assert calls[-1][1]["rules"] == {"version": 1, "global": [], "project": []}



@pytest.mark.parametrize("legacy_format", ["plain", "json"])
def test_near_full_legacy_store_reaches_wire_without_rewrite(transport, legacy_format):
    import json
    from mixar.modules.space_mixie_chat.core.rules import rules_snapshot

    scene, handler, calls = transport
    if legacy_format == "plain":
        raw = "x" * 9999
        text = raw
    else:
        envelope = json.dumps([{"text": "", "enabled": True}], separators=(",", ":"))
        text = "x" * (9999 - len(envelope.encode("utf-8")))
        raw = json.dumps([{"text": text, "enabled": True}], separators=(",", ":"))
    scene.mixie_chat_rules = raw
    assert len(raw.encode("utf-8")) == 9999
    snapshot = rules_snapshot(scene)
    # IDs are transport metadata; imposing the persisted JSON limit here
    # would reject an untouched file merely because it used the older format.
    wire_bytes = json.dumps(snapshot["project"], separators=(",", ":")).encode("utf-8")
    assert len(wire_bytes) > 9999
    assert snapshot["project"][0]["text"] == text
    assert handler.start_stream("Keep working", "instance", "session")
    assert calls[-1][1]["rules"] == snapshot
    assert handler.start_input_stream("session", "respond", text="yes")
    assert calls[-1][1]["rules"] == snapshot
    assert scene.mixie_chat_rules == raw

    # Migration metadata must not prevent a toggle of a valid legacy store.
    updated = rules_api.update_rule(scene, rule_id=snapshot["project"][0]["id"], enabled=False)
    assert updated["success"]
    assert updated["rules_snapshot"]["project"] == [
        {**snapshot["project"][0], "enabled": False}
    ]

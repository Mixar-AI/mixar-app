# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replacing folders while a question is pending must refresh the input wire."""

import sys
from types import SimpleNamespace

import pytest

from mixar.modules.context_folder.core import attach, grants, indexer
from mixar.modules.context_folder.core.registry import FolderRegistry, set_registry_for_tests
from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.core import rules_global, session, turn_transport


class Folders(list):
    def add(self):
        item = SimpleNamespace(folder_id="", name="")
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


@pytest.mark.parametrize("action", ["respond", "modify", "submit"])
def test_answer_sends_replaced_and_removed_folders(tmp_path, monkeypatch, action):
    scene = SimpleNamespace(name="FolderScene", mixie_session_id="session",
                            mixie_chat_rules="", mixie_chat_messages=[],
                            mixie_context_folders=Folders())
    monkeypatch.setattr(sys.modules["bpy"].data, "scenes", {scene.name: scene})
    monkeypatch.setattr(rules_global, "_store_path", lambda: str(tmp_path / "rules.json"))
    monkeypatch.setattr(session, "get_session_manager", lambda: SimpleNamespace(
        get_state=lambda _: SessionState.IDLE))
    monkeypatch.setattr(turn_transport.turn_events, "expect", lambda *args: None)
    monkeypatch.setattr(turn_transport, "collect_user_preferences", lambda: {})
    sent = []
    monkeypatch.setattr(turn_transport, "command", lambda method, payload, *a, **kw:
                        sent.append((method, payload)))
    set_registry_for_tests(FolderRegistry(tmp_path / "registry.json"))
    grants.clear()
    indexer.clear_cache()
    try:
        empty = tmp_path / "New Folder"
        empty.mkdir()
        hero = tmp_path / "01-Hero-Project"
        hero.mkdir()
        (hero / "README.md").write_text("Lantern Plaza")
        handler = turn_transport.TurnTransport(scene.name)
        old_id = attach.attach_folder(scene, str(empty))["folder_id"]
        assert handler.start_stream("Create a character", "instance", "session")
        assert sent[-1][1]["folder_context"]["folders"][0]["file_count"] == 0
        attach.detach_folder(scene, old_id)
        new_id = attach.attach_folder(scene, str(hero))["folder_id"]
        # A question answer, not a fresh chat: reproduce the reported sequence.
        assert handler.start_input_stream("session", action, text="Create this")
        method, payload = sent[-1]
        assert method == "input" and payload["text"] == "Create this"
        folder = payload["folder_context"]["folders"][0]
        assert (folder["folder_id"], folder["name"], folder["file_count"]) == (
            new_id, "01-Hero-Project", 1)
        assert folder["notes"][0]["excerpt"] == "Lantern Plaza"
        assert grants.granted("session") == frozenset({new_id})
        attach.detach_folder(scene, new_id)
        assert handler.start_input_stream("session", action, text="Continue without folders")
        assert sent[-1][1]["folder_context"] == {"version": 1, "folders": []}
        assert not grants.granted("session")
    finally:
        set_registry_for_tests(None)
        grants.clear()
        indexer.clear_cache()

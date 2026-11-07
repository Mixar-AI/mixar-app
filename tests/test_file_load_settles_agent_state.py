# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A file opened after a mid-turn save starts idle (mixar-backend#1823).

The run and turn state are Scene properties, and ``SKIP_SAVE`` does nothing
for those: a file saved mid-turn stores BUSY and an open run. File > Open
showed a stuck "Responding…" pill and the reconnect checks treated the dead
run as live. ``file_handlers._on_load_post`` now settles every tab, the same
way a crash restore did (QA 2026-10-31), and keeps the transcript and the
saved turn cursor for explicit recovery.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.space_mixie_chat.core import file_handlers

ROOT = Path(__file__).resolve().parents[1]
CHAT_PROPS = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/properties/chat_props.py"
RECOVERY = ROOT / "src/scripts/mixar/modules/session_recovery/runtime.py"

RUNTIME_FIELDS = ("mixie_chat_state", "mixie_chat_is_busy", "mixie_run_open",
                  "mixie_run_id", "mixie_chat_active_turn_mode")


class _Session:
    def __init__(self):
        self.calls = []

    def set_run(self, scene, run_id, open_):
        self.calls.append(("run", scene.name, run_id, open_))
        scene.mixie_run_open, scene.mixie_run_id = open_, run_id

    def set_connected(self, scene):
        self.calls.append(("idle", scene.name))
        scene.mixie_chat_state, scene.mixie_chat_is_busy = "IDLE", False

    def set_disconnected(self, scene):
        self.calls.append(("offline", scene.name))
        scene.mixie_chat_state, scene.mixie_chat_is_busy = "OFFLINE", False


def _saved_mid_turn(name):
    return SimpleNamespace(
        name=name, mixie_session_id=f"sid-{name}", mixie_chat_state="BUSY",
        mixie_chat_is_busy=True, mixie_run_open=True, mixie_run_id="run-1",
        mixie_chat_messages=["user asks", "agent works"], loader_visible=True,
        cursor={"session_id": f"sid-{name}", "turn_id": "t1", "cursor": 4, "complete": False},
    )


class _Processor:
    def _clear_loader_bubbles(self, scene):
        scene.loader_visible = False


@pytest.fixture
def loaded(monkeypatch):
    import mixar.modules.space_mixie_chat.core.jsonrpc_client as jc
    import mixar.modules.space_mixie_chat.core.queue_processor as qp
    import mixar.modules.space_mixie_chat.core.session as session_mod

    session = _Session()
    client = SimpleNamespace(is_connected=True)
    scenes = [_saved_mid_turn("A"), _saved_mid_turn("B")]
    monkeypatch.setattr(session_mod, "get_session_manager", lambda: session)
    monkeypatch.setattr(jc, "get_jsonrpc_client", lambda: client)
    monkeypatch.setattr(qp, "get_event_processor", lambda: _Processor())
    monkeypatch.setattr(file_handlers.bpy, "data", SimpleNamespace(scenes=scenes), raising=False)
    return SimpleNamespace(session=session, client=client, scenes=scenes)


def test_a_file_saved_mid_turn_opens_idle_when_connected(loaded):
    file_handlers.settle_loaded_scenes()
    assert loaded.session.calls == [("run", "A", "", False), ("idle", "A"),
                                    ("run", "B", "", False), ("idle", "B")]
    for scene in loaded.scenes:
        assert (scene.mixie_chat_state, scene.mixie_chat_is_busy, scene.mixie_run_open) == (
            "IDLE", False, False)
        assert scene.loader_visible is False  # no "Executing…" spinner left running
        # Explicit recovery keeps working: transcript and cursor stay.
        assert scene.mixie_chat_messages == ["user asks", "agent works"]
        assert scene.cursor["cursor"] == 4 and scene.mixie_session_id == f"sid-{scene.name}"


def test_a_file_opened_offline_settles_offline(loaded):
    loaded.client.is_connected = False
    file_handlers.settle_loaded_scenes()
    assert ("offline", "A") in loaded.session.calls
    assert not any(call[0] == "idle" for call in loaded.session.calls)
    assert all(s.mixie_chat_state == "OFFLINE" and not s.mixie_run_open for s in loaded.scenes)


def test_one_bad_scene_does_not_stop_the_others(loaded):
    def boom(scene, run_id, open_):
        if scene.name == "A":
            raise RuntimeError("scene gone")
        _Session.set_run(loaded.session, scene, run_id, open_)

    loaded.session.set_run = boom
    file_handlers.settle_loaded_scenes()
    assert loaded.scenes[1].mixie_chat_state == "IDLE"


def test_load_post_settles_and_crash_restore_reuses_it():
    source = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/file_handlers.py").read_text()
    body = source[source.index("def _on_load_post"):source.index("def _select_tab_for_mode")]
    assert "settle_loaded_scenes()" in body
    # A crash restore reads its file through load_post: no second copy there.
    assert "set_run" not in RECOVERY.read_text().split("def _after_restore")[1].split("\ndef ")[0]


def test_runtime_state_props_do_not_claim_skip_save():
    """SKIP_SAVE is an operator-property option; on a Scene property it is a
    no-op that read as "never persisted" and hid this bug."""
    source = CHAT_PROPS.read_text()
    for name in RUNTIME_FIELDS:
        start = source.index(f"bpy.types.Scene.{name} = ")
        block = source[start:source.index("\n    )\n", start)]
        assert "options={'SKIP_SAVE'" not in block, name

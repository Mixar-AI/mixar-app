# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn checkpoints (core/turn_checkpoints.py): a whole-document snapshot
before every fresh turn, deduplicated and pruned per session, and a restore
that keeps a safety copy, reads the snapshot with the recover flag, gives a
titled project its path back, and rewinds the backend conversation."""

import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

_SRC_ROOT = Path(__file__).parents[1] / "src" / "scripts"
_MIXAR_ROOT = _SRC_ROOT / "mixar"
_MODULES_ROOT = _MIXAR_ROOT / "modules"
_CHAT_ROOT = _MODULES_ROOT / "space_mixie_chat"
_CORE_ROOT = _CHAT_ROOT / "core"

if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))


class FakeSession:
    def __init__(self, state="idle", run_open=False, connected=True):
        self.state = SimpleNamespace(value=state)
        self._run_open = run_open
        self._connected = connected
        self.calls = []

    def get_state(self, scene):
        return self.state

    def run_open(self, scene):
        return self._run_open

    def is_connected(self, scene):
        return self._connected

    def set_run(self, scene, run_id, open_):
        self.calls.append(("set_run", run_id, open_))

    def clear_streaming(self):
        self.calls.append(("clear_streaming",))

    def set_connected(self, scene):
        self.calls.append(("set_connected",))

    def get_session_id(self, scene):
        return getattr(scene, "mixie_session_id", "")

    def clear_session_id(self, scene):
        scene.mixie_session_id = ""
        self.calls.append(("clear_session_id",))


@pytest.fixture
def tc(monkeypatch, tmp_path):
    """Load core/turn_checkpoints.py with its lazy neighbours stubbed."""
    for name, path in (
        ("mixar", _MIXAR_ROOT),
        ("mixar.modules", _MODULES_ROOT),
        ("mixar.modules.space_mixie_chat", _CHAT_ROOT),
        ("mixar.modules.space_mixie_chat.core", _CORE_ROOT),
    ):
        package = ModuleType(name)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, package)

    project_dir = tmp_path / "projects"
    project_dir.mkdir()
    bpy = MagicMock(name="bpy")
    bpy.data.filepath = str(project_dir / "lamp.mixar")
    bpy.data.scenes = []
    monkeypatch.setitem(sys.modules, "bpy", bpy)

    session = FakeSession()
    stub = {
        "mixar.modules.space_mixie_chat.core.session": {"get_session_manager": lambda: session},
        "mixar.modules.space_mixie_chat.core.turn_events": {"drop_scene": MagicMock()},
        "mixar.modules.space_mixie_chat.core.ui_utils": {"bump_layout_epoch": MagicMock(), "redraw_chat_areas": MagicMock()},
        "mixar.modules.space_mixie_chat.core.markdown_parser": {"clear_incremental_cache": MagicMock()},
        "mixar.modules.space_mixie_chat.core.message_helpers": {"add_agent_message": MagicMock()},
        "mixar.modules.common": {},
        "mixar.modules.common.agent_rpc": {},
        "mixar.modules.common.agent_rpc.client": {"request": MagicMock()},
    }
    for name, attrs in stub.items():
        module = ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)

    module_name = "mixar.modules.space_mixie_chat.core.turn_checkpoints"
    spec = importlib.util.spec_from_file_location(module_name, _CORE_ROOT / "turn_checkpoints.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "checkpoints_root", lambda: str(tmp_path / "checkpoints"))
    monkeypatch.setattr(module, "DEV_MODE", False)
    module.SessionState = SimpleNamespace(IDLE=session.state)   # can_restore compares by identity
    module._has_cache.clear()

    # save_as_mainfile writes whatever the test says the document holds.
    document = {"bytes": b"scene-v1"}

    def save_as(filepath="", copy=False, **_kw):
        with open(filepath, "wb") as f:
            f.write(document["bytes"])
        return {'FINISHED'}

    bpy.ops.wm.save_as_mainfile.side_effect = save_as
    return SimpleNamespace(m=module, bpy=bpy, session=session, document=document)


def _scene(session_id="sess-1", users=1):
    messages = [SimpleNamespace(sender="USER", text=f"m{i}") for i in range(users)]
    return SimpleNamespace(name="Scene", mixie_session_id=session_id, mixie_chat_messages=messages,
                           mixie_chat_user_has_engaged=True)


# --------------------------------------------------------------------------- #
#  Capture
# --------------------------------------------------------------------------- #


def test_capture_writes_a_snapshot_and_a_record(tc):
    scene = _scene(users=2)
    record = tc.m.capture(scene, "add a chandelier\nplease")
    assert record["turn_index"] == 3 and record["label"] == "add a chandelier please"
    assert record["kind"] == "turn" and record["request_id"] == "" and not record["session_was_new"]
    assert record["original_path"] == tc.bpy.data.filepath and record["bytes"] == len(b"scene-v1")
    path = os.path.join(tc.m.session_dir("sess-1"), record["file"])
    assert path.endswith(".mixar") and open(path, "rb").read() == b"scene-v1"
    kwargs = tc.bpy.ops.wm.save_as_mainfile.call_args.kwargs
    assert kwargs["copy"] is True and kwargs["compress"] is True and kwargs["filepath"].endswith(".tmp.mixar")
    assert tc.m.list_checkpoints("sess-1")[0]["id"] == record["id"]
    assert tc.m.has_checkpoints("sess-1") is True


def test_capture_assigns_a_session_to_a_new_chat_and_remembers_it(tc):
    scene = _scene(session_id="", users=0)
    record = tc.m.capture(scene, "first message")
    assert scene.mixie_session_id and record["session_id"] == scene.mixie_session_id
    assert record["session_was_new"] is True and record["turn_index"] == 1


def test_identical_documents_share_one_file(tc):
    scene = _scene()
    first = tc.m.capture(scene, "one")
    second = tc.m.capture(scene, "two")
    assert first["file"] == second["file"] and first["id"] != second["id"]
    files = [f for f in os.listdir(tc.m.session_dir("sess-1")) if f.endswith(".mixar")]
    assert files == [first["file"]]
    tc.document["bytes"] = b"scene-v2"
    third = tc.m.capture(scene, "three")
    assert third["file"] != first["file"] and len(tc.m.list_checkpoints("sess-1")) == 3


def test_prune_keeps_the_newest_and_removes_orphaned_files(tc, monkeypatch):
    monkeypatch.setattr(tc.m, "MAX_PER_SESSION", 3)
    scene = _scene()
    records = []
    for i in range(5):
        tc.document["bytes"] = f"v{i}".encode()
        records.append(tc.m.capture(scene, f"turn {i}"))
    kept = tc.m.list_checkpoints("sess-1")
    assert [r["label"] for r in kept] == ["turn 4", "turn 3", "turn 2"]
    files = {f for f in os.listdir(tc.m.session_dir("sess-1")) if f.endswith(".mixar")}
    assert files == {r["file"] for r in records[2:]}


def test_capture_failure_never_raises(tc):
    tc.bpy.ops.wm.save_as_mainfile.side_effect = RuntimeError("no window")
    assert tc.m.capture(_scene(), "x") is None
    assert tc.m.list_checkpoints("sess-1") == []


def test_bind_request_persists_the_command_id(tc):
    scene = _scene()
    record = tc.m.capture(scene, "one")
    tc.m.bind_request(record, "cmd-123")
    assert tc.m.get_checkpoint("sess-1", record["id"])["request_id"] == "cmd-123"


def test_listing_skips_records_whose_file_is_gone(tc):
    scene = _scene()
    record = tc.m.capture(scene, "one")
    os.remove(os.path.join(tc.m.session_dir("sess-1"), record["file"]))
    assert tc.m.list_checkpoints("sess-1") == []


# --------------------------------------------------------------------------- #
#  Restore
# --------------------------------------------------------------------------- #


def test_can_restore_requires_an_idle_session_with_no_open_run(tc):
    scene = _scene()
    assert tc.m.can_restore(scene) == (True, "")
    tc.session._run_open = True
    assert tc.m.can_restore(scene)[0] is False
    tc.session._run_open = False
    tc.session.state = SimpleNamespace(value="busy")
    assert tc.m.can_restore(scene)[0] is False


def _prepare_restore(tc, monkeypatch, scene):
    tc.document["bytes"] = b"scene-turn-2"
    target = tc.m.capture(scene, "turn two")
    tc.m.bind_request(target, "cmd-turn-2")
    tc.document["bytes"] = b"scene-now"
    sent = []
    monkeypatch.setattr(tc.m, "_send_backend", lambda sid, calls: sent.append((sid, calls)))
    seen = {}

    def recover(filepath=""):
        seen["restoring"] = tc.m.is_restoring()
        seen["bytes"] = open(filepath, "rb").read()
        return {'FINISHED'}

    tc.bpy.ops.wm.recover_auto_save.side_effect = recover
    tc.bpy.data.scenes = [scene]
    return target, sent, seen


def test_restore_keeps_a_safety_copy_recovers_the_snapshot_and_saves_the_path_back(tc, monkeypatch):
    scene = _scene(users=4)
    target, sent, seen = _prepare_restore(tc, monkeypatch, scene)

    ok, message = tc.m.restore(scene, target["id"])
    assert ok and "turn 5" in message
    assert seen == {"restoring": True, "bytes": b"scene-turn-2"} and tc.m.is_restoring() is False
    # The safety copy is the newest record, bound to a fresh bookmark id.
    newest = tc.m.list_checkpoints("sess-1")[0]
    assert newest["kind"] == "safety" and newest["request_id"] and newest["turn_index"] == 4
    # Titled project: saved back to its own path, exactly once, after the read.
    saves = [c.kwargs for c in tc.bpy.ops.wm.save_as_mainfile.call_args_list if not c.kwargs.get("copy")]
    assert saves == [{"filepath": tc.bpy.data.filepath}]
    assert open(tc.bpy.data.filepath, "rb").read() == b"scene-now"
    # Backend: bookmark the safety copy, then rewind to the restored turn.
    assert len(sent) == 1
    sid, calls = sent[0]
    assert sid == "sess-1"
    assert [m for m, _ in calls] == ["checkpoint.mark", "checkpoint.rewind"]
    assert calls[0][1] == {"session_id": "sess-1", "request_id": newest["request_id"]}
    assert calls[1][1] == {"session_id": "sess-1", "request_id": "cmd-turn-2"}
    assert ("set_run", "", False) in tc.session.calls and ("set_connected",) in tc.session.calls


def test_untitled_project_is_parked_in_the_session_working_file(tc, monkeypatch):
    tc.bpy.data.filepath = ""
    scene = _scene()
    target, sent, _ = _prepare_restore(tc, monkeypatch, scene)
    ok, _ = tc.m.restore(scene, target["id"])
    assert ok
    saves = [c.kwargs for c in tc.bpy.ops.wm.save_as_mainfile.call_args_list if not c.kwargs.get("copy")]
    assert saves == [{"filepath": tc.m.working_file("sess-1")}]
    # A later Ctrl-S lands there, never on a checkpoint file.
    assert not saves[0]["filepath"].endswith(target["file"])
    assert tc.m.list_checkpoints("sess-1")   # the working file is not a checkpoint


def test_header_imports_core_at_the_right_depth():
    # ui/header.py sits one level below the package: ``..core`` is the
    # package's core; ``...core`` raised in the live app and blanked the
    # whole header after the history button.
    source = (_CHAT_ROOT / "ui" / "header.py").read_text(encoding="utf-8")
    assert "from ..core import turn_checkpoints" in source
    assert "from ...core import turn_checkpoints" not in source


def test_restore_of_a_pre_conversation_snapshot_starts_a_fresh_session(tc, monkeypatch):
    scene = _scene(session_id="", users=0)
    tc.document["bytes"] = b"empty"
    target = tc.m.capture(scene, "first")          # assigns the session id, session_was_new
    tc.m.bind_request(target, "cmd-1")
    session_id = scene.mixie_session_id
    scene.mixie_chat_messages.append(SimpleNamespace(sender="USER", text="first"))
    tc.document["bytes"] = b"after-turn-1"
    sent = []
    monkeypatch.setattr(tc.m, "_send_backend", lambda sid, calls: sent.append((sid, calls)))
    tc.bpy.ops.wm.recover_auto_save.side_effect = lambda filepath="": {'FINISHED'}
    tc.bpy.data.scenes = [scene]

    ok, _ = tc.m.restore(scene, target["id"])
    assert ok and ("clear_session_id",) in tc.session.calls and scene.mixie_session_id == ""
    # Only the safety copy is bookmarked (under the old session); no rewind.
    assert [m for m, _ in sent[0][1]] == ["checkpoint.mark"] and sent[0][0] == session_id


def test_restore_refusals(tc, monkeypatch):
    scene = _scene()
    assert tc.m.restore(scene, "missing")[0] is False
    target, _, _ = _prepare_restore(tc, monkeypatch, scene)
    tc.session._run_open = True
    ok, reason = tc.m.restore(scene, target["id"])
    assert ok is False and "building" in reason
    tc.bpy.ops.wm.recover_auto_save.assert_not_called()


def test_a_failed_read_reports_and_clears_the_restoring_flag(tc, monkeypatch):
    scene = _scene()
    target, sent, _ = _prepare_restore(tc, monkeypatch, scene)
    tc.bpy.ops.wm.recover_auto_save.side_effect = RuntimeError("corrupt")
    ok, message = tc.m.restore(scene, target["id"])
    assert ok is False and "Could not read" in message and tc.m.is_restoring() is False
    assert sent == []


def test_cancelled_read_does_not_save_or_rewind_the_conversation(tc, monkeypatch):
    scene = _scene()
    target, sent, _ = _prepare_restore(tc, monkeypatch, scene)
    tc.bpy.ops.wm.recover_auto_save.side_effect = lambda **kwargs: {'CANCELLED'}
    tc.bpy.ops.wm.save_as_mainfile.reset_mock()

    ok, message = tc.m.restore(scene, target["id"])

    assert ok is False and "Could not read" in message
    assert tc.m.is_restoring() is False
    assert sent == []
    assert tc.session.calls == []
    assert all(call.kwargs.get("copy") for call in tc.bpy.ops.wm.save_as_mainfile.call_args_list)


def test_restore_fences_the_session_so_recovery_does_not_replay_undone_turns(tc, monkeypatch):
    scene = _scene(users=3)
    target, _, _ = _prepare_restore(tc, monkeypatch, scene)
    assert tc.m.restore(scene, target["id"])[0]
    sys.modules["mixar.modules.space_mixie_chat.core.turn_events"].drop_scene.assert_called_once_with("Scene")


def test_a_refused_backend_reply_is_reported_as_a_failure(tc, monkeypatch):
    import threading
    request = sys.modules["mixar.modules.common.agent_rpc.client"].request
    request.side_effect = None
    request.return_value = {"status": "failure", "message": "This turn is unknown to the backend"}
    notices = []
    monkeypatch.setattr(tc.m, "_notify", lambda scene_name, text: notices.append(text))
    tc.bpy.data.scenes = [_scene()]
    tc.m._send_backend("sess-1", [("checkpoint.rewind", {"session_id": "sess-1", "request_id": "x"})])
    for _ in range(200):
        if not tc.m.rewind_in_flight():
            break
        threading.Event().wait(0.01)
    assert notices and "unknown to the backend" in notices[0]


def test_restore_runs_the_file_ops_in_the_main_window(tc, monkeypatch):
    main = SimpleNamespace(screen=SimpleNamespace(is_temporary=False), name="main")
    island = SimpleNamespace(screen=SimpleNamespace(is_temporary=True), name="island")
    tc.bpy.context.window_manager.windows = [island, main]
    scene = _scene()
    target, _, _ = _prepare_restore(tc, monkeypatch, scene)
    assert tc.m.restore(scene, target["id"])[0]
    overrides = [c.kwargs.get("window") for c in tc.bpy.context.temp_override.call_args_list]
    assert overrides and all(w is main for w in overrides)


def test_restore_deferred_runs_on_a_timer_and_reports_failure_as_a_notice(tc, monkeypatch):
    scene = _scene()
    tc.bpy.data.scenes = SimpleNamespace(get=lambda name: scene)
    notices = []
    monkeypatch.setattr(tc.m, "_notify", lambda scene_name, text: notices.append(text))
    tc.m.restore_deferred("Scene", "missing")
    register = tc.bpy.app.timers.register
    assert register.called
    callback = register.call_args.args[0]
    assert callback() is None
    assert notices == ["Checkpoint not restored: Checkpoint not found"]


def test_backend_calls_block_sending_until_done(tc, monkeypatch):
    import threading
    request = sys.modules["mixar.modules.common.agent_rpc.client"].request
    gate = threading.Event()
    request.side_effect = lambda *a, **k: gate.wait(2)
    tc.bpy.data.scenes = [_scene()]
    tc.m._send_backend("sess-1", [("checkpoint.rewind", {"session_id": "sess-1", "request_id": "x"})])
    assert tc.m.rewind_in_flight() is True
    gate.set()
    for _ in range(200):
        if not tc.m.rewind_in_flight():
            break
        threading.Event().wait(0.01)
    assert tc.m.rewind_in_flight() is False
    assert request.call_args.args[0] == "checkpoint.rewind" and request.call_args.kwargs == {"mutation": True}


def test_a_bookmarkless_rewind_clears_the_session_id(tc, monkeypatch):
    """The backend only forks when the bookmark has a checkpoint id.
    `has_conversation: false` means NOTHING was forked, and the contract says
    the client clears its session id. It was deciding from its own local
    `session_was_new` instead -- a different question -- so a .blend carrying a
    session id whose backend thread was purged rolled the scene back while the
    agent kept remembering every reverted turn."""
    import threading
    request = sys.modules["mixar.modules.common.agent_rpc.client"].request
    request.side_effect = None
    request.return_value = {"status": "success", "has_conversation": False}
    notices, cleared = [], []
    monkeypatch.setattr(tc.m, "_notify", lambda scene_name, text: notices.append(text))
    monkeypatch.setattr(tc.m, "_clear_session_on_main",
                        lambda scene_name: cleared.append(scene_name))
    tc.bpy.data.scenes = [_scene()]

    tc.m._send_backend("sess-1", [("checkpoint.rewind", {"session_id": "sess-1", "request_id": "x"})])
    for _ in range(200):
        if not tc.m.rewind_in_flight():
            break
        threading.Event().wait(0.01)

    assert cleared, "has_conversation: false must clear the session id"
    assert not notices, "a bookmark-less rewind is not a failure"


def test_a_rewind_that_forked_leaves_the_session_alone(tc, monkeypatch):
    import threading
    request = sys.modules["mixar.modules.common.agent_rpc.client"].request
    request.side_effect = None
    request.return_value = {"status": "success", "has_conversation": True}
    cleared = []
    monkeypatch.setattr(tc.m, "_clear_session_on_main",
                        lambda scene_name: cleared.append(scene_name))
    tc.bpy.data.scenes = [_scene()]

    tc.m._send_backend("sess-1", [("checkpoint.rewind", {"session_id": "sess-1", "request_id": "x"})])
    for _ in range(200):
        if not tc.m.rewind_in_flight():
            break
        threading.Event().wait(0.01)

    assert not cleared


def _age(path, days):
    old = os.path.getmtime(path) - days * 86400.0
    for root, _dirs, files in os.walk(path):
        for name in files:
            os.utime(os.path.join(root, name), (old, old))
    os.utime(path, (old, old))


def test_stale_session_directories_are_retired(tc, monkeypatch):
    """Per-session pruning bounded ONE chat at 20 snapshots; nothing ever
    retired a session directory, and each snapshot is a whole document."""
    root = tc.m.checkpoints_root()
    for name in ("old-a", "old-b", "fresh"):
        d = tc.m.session_dir(name)
        with open(os.path.join(d, "x.mixar"), "w") as f:
            f.write("blend")
    _age(os.path.join(root, "old-a"), tc.m.MAX_AGE_DAYS + 1)
    _age(os.path.join(root, "old-b"), tc.m.MAX_AGE_DAYS + 1)

    assert tc.m.prune_sessions("live") == 2
    assert sorted(os.listdir(root)) == ["fresh"]


def test_the_live_session_is_never_retired(tc, monkeypatch):
    root = tc.m.checkpoints_root()
    d = tc.m.session_dir("live")
    with open(os.path.join(d, "x.mixar"), "w") as f:
        f.write("blend")
    _age(d, tc.m.MAX_AGE_DAYS + 5)

    assert tc.m.prune_sessions("live") == 0
    assert os.listdir(root) == ["live"]


def test_session_directories_are_capped_by_count_too(tc, monkeypatch):
    """Age alone does not bound the multiplication: a burst of chats in one
    week is exactly the case that fills the disk."""
    monkeypatch.setattr(tc.m, "MAX_SESSIONS", 3)
    root = tc.m.checkpoints_root()
    for i in range(6):
        d = tc.m.session_dir(f"chat-{i}")
        with open(os.path.join(d, "x.mixar"), "w") as f:
            f.write("blend")
        _age(d, 6 - i)          # chat-0 oldest, chat-5 newest

    removed = tc.m.prune_sessions("live")
    survivors = sorted(os.listdir(root))
    assert len(survivors) == 3 and removed == 3
    assert survivors == ["chat-3", "chat-4", "chat-5"]


def test_the_session_prune_runs_at_most_once_a_day(tc, monkeypatch):
    calls = []
    monkeypatch.setattr(tc.m, "prune_sessions", lambda keep="": calls.append(keep))
    tc.m._last_cleanup_day = -1
    tc.m._prune_sessions_once_per_day("sess-1")
    tc.m._prune_sessions_once_per_day("sess-1")
    assert calls == ["sess-1"]


def test_a_failing_session_prune_never_blocks_a_capture(tc, monkeypatch):
    def boom(keep=""):
        raise OSError("disk gone")
    monkeypatch.setattr(tc.m, "prune_sessions", boom)
    tc.m._last_cleanup_day = -1
    tc.m._prune_sessions_once_per_day("sess-1")     # must not raise

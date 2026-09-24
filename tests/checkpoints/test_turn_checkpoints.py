# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn checkpoints (core/turn_checkpoints.py): a whole-document snapshot
before every fresh turn, one timeline per chat where the chat length is the
position, revert/reapply that never mints copies of stored states, a tip and
hand-edit copies for what would otherwise be lost, a read with the recover
flag that gives a titled project its path back, and a backend rewind.

The disk budget across sessions lives in test_session_pruning.py."""

import os
from pathlib import Path
import sys
from types import SimpleNamespace

# The one source-level case below reads the real header; the rest go through `tc`.
_CHAT_ROOT = (Path(__file__).parents[2] / "src" / "scripts" / "mixar"
              / "modules" / "space_mixie_chat")


from helpers import _scene, _send, _turns  # noqa: F401,E402


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
    _send(scene)
    second = tc.m.capture(scene, "two")
    _send(scene)
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
        _send(scene)
    kept = tc.m.list_checkpoints("sess-1")
    assert [r["label"] for r in kept] == ["turn 4", "turn 3", "turn 2"]
    files = {f for f in os.listdir(tc.m.session_dir("sess-1")) if f.endswith(".mixar")}
    assert files == {r["file"] for r in records[2:]}


def test_capture_failure_never_raises(tc):
    tc.bpy.ops.wm.save_as_mainfile.side_effect = RuntimeError("no window")
    assert tc.m.capture(_scene(), "x") is None
    assert tc.m.list_checkpoints("sess-1") == []


def test_capture_keeps_a_snapshot_saved_with_pack_errors(tc):
    # Autopack + a missing texture: Blender writes the copy, then bpy.ops
    # raises for the "Unable to pack file" reports. The checkpoint must stay.
    real_save = tc.bpy.ops.wm.save_as_mainfile.side_effect

    def save_then_report(**kw):
        real_save(**kw)
        raise RuntimeError("Error: Unable to pack file, source path '/c/x.png' not found")

    tc.bpy.ops.wm.save_as_mainfile.side_effect = save_then_report
    record = tc.m.capture(_scene(), "x")
    assert record is not None
    assert [r["id"] for r in tc.m.list_checkpoints("sess-1")] == [record["id"]]
    assert os.path.isfile(tc.m._file_path(record))
    assert not [f for f in os.listdir(tc.m.session_dir("sess-1")) if f.endswith(".tmp.mixar")]


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
    """One captured-and-sent turn; the document has moved on since."""
    tc.document["bytes"] = b"scene-turn-2"
    target = tc.m.capture(scene, "turn two")
    tc.m.bind_request(target, "cmd-turn-2")
    _send(scene, "turn two")
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


def test_revert_keeps_the_tip_recovers_the_snapshot_and_never_writes_the_project(tc, monkeypatch):
    scene = _scene(users=4)
    target, sent, seen = _prepare_restore(tc, monkeypatch, scene)
    project = tc.bpy.data.filepath
    open(project, "wb").write(b"artist-hour-of-work")

    ok, message = tc.m.restore(scene, target["id"])
    assert ok and message == "Reverted turn 5"
    assert seen == {"restoring": True, "bytes": b"scene-turn-2"} and tc.m.is_restoring() is False
    # Leaving the tip: the state after turn 5 exists nowhere else, so it is
    # kept as the tip record, bound to a fresh bookmark id.
    newest = tc.m.list_checkpoints("sess-1")[0]
    assert newest["kind"] == "tip" and newest["request_id"] and newest["turn_index"] == 5
    assert open(os.path.join(tc.m.session_dir("sess-1"), newest["file"]), "rb").read() == b"scene-now"
    # The project file on disk is untouched; the document is re-titled in
    # memory to its own path (and marked modified by the native operator).
    saves = [c.kwargs for c in tc.bpy.ops.wm.save_as_mainfile.call_args_list if not c.kwargs.get("copy")]
    assert saves == []
    assert open(project, "rb").read() == b"artist-hour-of-work"
    tc.bpy.ops.mixie_chat.retitle_document.assert_called_once_with(filepath=project)
    # Blender's queued file-read notifier marks the document saved after the
    # operator returns (and after a zero-interval timer), so a short timer
    # re-titles until the modified flag has held across two ticks.
    deferred = tc.bpy.app.timers.register.call_args
    assert deferred.kwargs == {"first_interval": 0.05}
    tick = deferred.args[0]
    tc.bpy.data.is_dirty = False          # the notifier pass cleared it
    assert tick() == 0.05
    assert tc.bpy.ops.mixie_chat.retitle_document.call_count == 2
    assert tc.bpy.ops.mixie_chat.retitle_document.call_args == ((), {"filepath": project})
    tc.bpy.data.is_dirty = True
    assert tick() == 0.05 and tick() is None   # held twice: done
    assert tc.bpy.ops.mixie_chat.retitle_document.call_count == 2
    # Backend: bookmark the tip, then rewind to the reverted turn.
    assert len(sent) == 1
    sid, calls = sent[0]
    assert sid == "sess-1"
    assert [m for m, _ in calls] == ["checkpoint.mark", "checkpoint.rewind"]
    assert calls[0][1] == {"session_id": "sess-1", "request_id": newest["request_id"]}
    assert calls[1][1] == {"session_id": "sess-1", "request_id": "cmd-turn-2"}
    assert ("set_run", "", False) in tc.session.calls and ("set_connected",) in tc.session.calls


def test_modified_retag_is_bounded(tc):
    tc.bpy.data.is_dirty = False
    tick = tc.m._keep_modified("/p/lamp.mixar", ticks=3)
    assert tick() == 0.05 and tick() == 0.05 and tick() is None
    assert tc.bpy.ops.mixie_chat.retitle_document.call_count == 3


def test_untitled_project_stays_untitled(tc, monkeypatch):
    tc.bpy.data.filepath = ""
    scene = _scene()
    target, sent, _ = _prepare_restore(tc, monkeypatch, scene)
    ok, _ = tc.m.restore(scene, target["id"])
    assert ok
    # No hidden working file, no write at all: Ctrl-S must open Save As.
    saves = [c.kwargs for c in tc.bpy.ops.wm.save_as_mainfile.call_args_list if not c.kwargs.get("copy")]
    assert saves == []
    tc.bpy.ops.mixie_chat.retitle_document.assert_called_once_with(filepath="")
    tc.bpy.data.is_dirty = False
    tc.bpy.app.timers.register.call_args.args[0]()
    assert tc.bpy.ops.mixie_chat.retitle_document.call_args == ((), {"filepath": ""})
    assert not hasattr(tc.m, "working_file")
    assert tc.m.list_checkpoints("sess-1")


def test_snapshots_keep_relative_paths_anchored_to_the_project(tc):
    tc.m.capture(_scene(), "turn")
    kwargs = tc.bpy.ops.wm.save_as_mainfile.call_args.kwargs
    assert kwargs["copy"] is True and kwargs["relative_remap"] is False


def test_safety_copies_are_pruned_only_among_themselves(tc, monkeypatch):
    monkeypatch.setattr(tc.m, "MAX_PER_SESSION", 2)
    monkeypatch.setattr(tc.m, "MAX_SAFETY_PER_SESSION", 1)
    scene = _scene()
    kinds = []
    for index, kind in enumerate(["safety", "turn", "turn", "turn", "safety", "turn"]):
        tc.document["bytes"] = f"doc-{index}".encode()
        record = tc.m.capture(scene, f"{kind} {index}", kind=kind)
        if kind == "turn":
            _send(scene)
        kinds.append((record["kind"], record["file"]))
    kept = [(i["kind"], i["file"]) for i in sorted(tc.m.list_checkpoints("sess-1"), key=tc.m._order)]
    # Newest 2 turns and the newest safety copy survive; a run of turns did
    # not evict the safety copy, and the pruned files are gone from disk.
    assert kept == [kinds[3], kinds[4], kinds[5]]
    import os
    assert not os.path.exists(os.path.join(tc.m.session_dir("sess-1"), kinds[0][1]))
    assert os.path.exists(os.path.join(tc.m.session_dir("sess-1"), kinds[4][1]))




def test_restore_of_a_pre_conversation_snapshot_starts_a_fresh_session(tc, monkeypatch):
    scene = _scene(session_id="", users=0)
    tc.document["bytes"] = b"empty"
    target = tc.m.capture(scene, "first")          # assigns the session id, session_was_new
    tc.m.bind_request(target, "cmd-1")
    session_id = scene.mixie_session_id
    _send(scene, "first")
    tc.document["bytes"] = b"after-turn-1"
    sent = []
    monkeypatch.setattr(tc.m, "_send_backend", lambda sid, calls: sent.append((sid, calls)))
    tc.bpy.ops.wm.recover_auto_save.side_effect = lambda filepath="": {'FINISHED'}
    tc.bpy.data.scenes = [scene]

    ok, _ = tc.m.restore(scene, target["id"])
    assert ok and ("clear_session_id",) in tc.session.calls and scene.mixie_session_id == ""
    # Only the tip is bookmarked (under the old session); no rewind.
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
    monkeypatch.setattr(tc.m.checkpoint_backend, "_notify", lambda scene_name, text: notices.append(text))
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
    monkeypatch.setattr(tc.m.checkpoint_backend, "_notify", lambda scene_name, text: notices.append(text))
    monkeypatch.setattr(tc.m.checkpoint_backend, "_clear_session_on_main",
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
    monkeypatch.setattr(tc.m.checkpoint_backend, "_clear_session_on_main",
                        lambda scene_name: cleared.append(scene_name))
    tc.bpy.data.scenes = [_scene()]

    tc.m._send_backend("sess-1", [("checkpoint.rewind", {"session_id": "sess-1", "request_id": "x"})])
    for _ in range(200):
        if not tc.m.rewind_in_flight():
            break
        threading.Event().wait(0.01)

    assert not cleared


def test_restore_operator_runs_in_exec_only_and_the_native_retitle_never_writes():
    ops = (_CHAT_ROOT / "ui" / "operators" / "checkpoint_ops.py").read_text(encoding="utf-8")
    restore_cls = ops[ops.index("class MIXIE_CHAT_OT_restore_checkpoint"):]
    # The card's second click is the confirmation: no invoke() dialog, no
    # REGISTER (nothing to redo from the F3 history), INTERNAL.
    assert "def invoke(" not in restore_cls and "invoke_confirm" not in ops
    assert "bl_options = {'INTERNAL'}" in restore_cls
    # The Blender menu (EXEC rows, no dialog) is gone: the native card lists
    # the checkpoints and arms a row before acting.
    assert "class MIXIE_CHAT_MT_checkpoints" not in ops
    assert "class MIXIE_CHAT_OT_show_checkpoints" in ops
    sync = ops[ops.index("def sync_checkpoint_entries"):ops.index("class MIXIE_CHAT_OT_show_checkpoints")]
    assert "wm.mixie_chat_history_mode = 'CHECKPOINTS'" in sync
    assert "wm.mixie_chat_history_locked = not allowed" in sync
    assert "turn_checkpoints.checkpoint_session_id(scene)" in sync
    native = (Path(__file__).parents[2] / "src/source/blender/editors/space_mixie_chat"
              / "mixie_chat_document_ops.cc").read_text(encoding="utf-8")
    assert "MIXIE_CHAT_OT_retitle_document" in native
    assert "WM_file_tag_modified()" in native
    assert "STRNCPY(bmain->filepath, filepath)" in native
    import re
    code = re.sub(r"/\*.*?\*/", "", native, flags=re.S)            # comments explain, code must not write
    code = "\n".join(line.split("//")[0] for line in code.splitlines())
    for forbidden in ("BLO_write", "wm_file_write", "WM_file_write", "save_as_mainfile", "fopen"):
        assert forbidden not in code
    core = (_CHAT_ROOT / "core" / "turn_checkpoints.py").read_text(encoding="utf-8")
    restore = core[core.index("def restore("):core.index("def restore_deferred(")]
    assert "save_as_mainfile" not in restore
    assert "_retitle(original_path)" in restore and "timers.register" in restore
    # Every read is preceded by the bubble purge, keep-capture or not.
    assert restore.index("_close_bubble_windows()") < restore.index("recover_auto_save")


def test_native_card_checkpoint_mode_arms_before_restoring():
    chat = Path(__file__).parents[2] / "src/source/blender/editors/space_mixie_chat"
    events = (chat / "mixie_chat_history_events.cc").read_text(encoding="utf-8")
    arm = events[events.index("static void history_arm_or_restore_row"):events.index("static void history_arm_or_delete_row")]
    # First click arms (stores the id), only a matching second click dispatches.
    assert 'STREQ(rt->history_confirm_id, checkpoint_id)' in arm
    assert '"mixie_chat.restore_checkpoint", "checkpoint_id"' in arm
    assert arm.index("BLI_strncpy(rt->history_confirm_id") > arm.index("mixie_chat_history_dispatch_id_op")
    # The card's drawing is split: layout (overlay), chrome, rows.
    overlay = "".join((chat / name).read_text(encoding="utf-8") for name in
                      ("mixie_chat_history_overlay.cc", "mixie_chat_history_chrome.cc",
                       "mixie_chat_history_rows.cc"))
    # The armed prompt comes from Python per row ("Revert turns 3–5?").
    assert "entry.action[0] ? entry.action" in overlay and '"Checkpoints"' in overlay
    assert "Reverted turns move below" in overlay and "Nothing is written to your file" in overlay
    assert "Here now" not in overlay and "Go back?" not in overlay
    targets = (chat / "mixie_chat_qa_targets.cc").read_text(encoding="utf-8")
    assert '"chat_checkpoint_row"' in targets and '"chat_history_row"' in targets
    bubble = (chat.parent / "space_agent_bubble" / "space_agent_bubble.cc").read_text(encoding="utf-8")
    assert '"mixie_chat.show_checkpoints"' in bubble and "MIXIE_CHAT_MT_checkpoints" not in bubble


def test_a_transient_sharing_violation_on_rename_is_retried(tc, monkeypatch):
    """Windows: a just-written snapshot or index can be held by a scanner for
    a moment and the rename fails with PermissionError; a short retry rides
    it out, a persistent one still surfaces (capture returns None)."""
    import os as _os
    real_replace = _os.replace
    attempts = {"n": 0}

    def flaky(src, dst):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real_replace(src, dst)

    monkeypatch.setattr(tc.m.checkpoint_store.os, "replace", flaky)
    monkeypatch.setattr(tc.m.checkpoint_store, "REPLACE_RETRY_SECONDS", 0.0)
    record = tc.m.capture(_scene(), "held by a scanner")
    assert record is not None and attempts["n"] >= 3
    assert os.path.isfile(os.path.join(tc.m.session_dir("sess-1"), record["file"]))

    def stuck(src, dst):
        raise PermissionError(32, "still held")
    monkeypatch.setattr(tc.m.checkpoint_store.os, "replace", stuck)
    assert tc.m.capture(_scene(), "never released") is None

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The checkpoint timeline: the chat length is the position, reverting moves
a turn (and every later one) below, reapplying brings it back from the next
turn's snapshot or the tip, hand edits on a reverted position become a safety
copy judged from the undo stack, a new message drops the reverted turns, and
the native card's sections and prompts follow the same split.

Capture, restore mechanics and the backend rewind live in
test_turn_checkpoints.py; the disk budget in test_session_pruning.py."""

import os
from pathlib import Path

from helpers import _edit, _scene, _send, _turns  # noqa: E402

_CHAT_ROOT = (Path(__file__).parents[2] / "src" / "scripts" / "mixar"
              / "modules" / "space_mixie_chat")


def _prepare_timeline(tc, monkeypatch, scene, turns=3):
    records = _turns(tc, scene, turns)
    sent = []
    monkeypatch.setattr(tc.m, "_send_backend", lambda sid, calls: sent.append((sid, calls)))
    reads = []

    def recover(filepath=""):
        reads.append(open(filepath, "rb").read())
        # The read resets the undo stack: a fresh stamp.
        tc.bpy.context.window_manager.mixie_chat_undo_stamp = f"read-{len(reads)}"
        return {'FINISHED'}

    tc.bpy.ops.wm.recover_auto_save.side_effect = recover
    tc.bpy.data.scenes = [scene]
    return records, sent, reads


def _lists(tc, scene):
    line = tc.m.timeline("sess-1", scene)
    return ([r["turn_index"] for r in line["applied"]], [r["turn_index"] for r in line["reverted"]],
            line["tip"] is not None, [r["label"] for r in line["safety"]])


def _kinds(tc):
    return sorted(i["kind"] for i in tc.m.list_checkpoints("sess-1"))


def test_the_chat_length_is_the_position(tc, monkeypatch):
    scene = _scene(users=0)
    _turns(tc, scene, 3)
    assert _lists(tc, scene) == ([3, 2, 1], [], False, [])
    del scene.mixie_chat_messages[2:]           # what a revert of turn 3 leaves in the chat
    # Turn 3 is above the position but its state after it was never stored
    # (no tip): a row that cannot be reapplied is not shown.
    assert _lists(tc, scene) == ([2, 1], [], False, [])
    tc.document["bytes"] = b"tip"
    tc.m.capture(scene, "after turn 3", kind="tip")
    assert _lists(tc, scene) == ([2, 1], [3], True, [])
    del scene.mixie_chat_messages[:]
    assert _lists(tc, scene) == ([], [3, 2, 1], True, [])


def test_reverting_moves_the_turn_below_and_reapplying_brings_it_back_without_copies(tc, monkeypatch):
    scene = _scene(users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene)
    turn3 = records[2]

    ok, message = tc.m.restore(scene, turn3["id"])
    assert ok and message == "Reverted turn 3" and reads == [b"before-turn-3"]
    del scene.mixie_chat_messages[2:]           # the read put the shorter chat back
    assert _lists(tc, scene) == ([2, 1], [3], True, [])
    tip = tc.m.timeline("sess-1", scene)["tip"]
    assert tip["label"] == "after turn 3" and tip["turn_index"] == 3
    assert open(os.path.join(tc.m.session_dir("sess-1"), tip["file"]), "rb").read() == b"tip"
    assert [m for m, _ in sent[-1][1]] == ["checkpoint.mark", "checkpoint.rewind"]
    assert sent[-1][1][1][1]["request_id"] == "cmd-3"

    # Same row again: it now sits in Reverted turns, so the click reapplies
    # it from the tip. No new record of any kind.
    ok, message = tc.m.restore(scene, turn3["id"])
    assert ok and message == "Reapplied turn 3" and reads[-1] == b"tip"
    _send(scene, "turn 3")                       # the read put the full chat back
    assert _lists(tc, scene) == ([3, 2, 1], [], True, [])
    assert _kinds(tc) == ["tip", "turn", "turn", "turn"]
    assert [m for m, _ in sent[-1][1]] == ["checkpoint.rewind"]
    assert sent[-1][1][0][1]["request_id"] == tip["request_id"]

    # And again: nothing was done since the tip came back, so the stored tip
    # still holds and is not captured a second time.
    saves_before = tc.bpy.ops.wm.save_as_mainfile.call_count
    ok, message = tc.m.restore(scene, turn3["id"])
    assert ok and message == "Reverted turn 3"
    assert tc.bpy.ops.wm.save_as_mainfile.call_count == saves_before
    assert _kinds(tc) == ["tip", "turn", "turn", "turn"]


def test_reverting_an_earlier_turn_takes_every_later_turn_with_it(tc, monkeypatch):
    scene = _scene(users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene, turns=5)
    line = tc.m.timeline("sess-1", scene)
    assert tc.m.describe_jump(line, records[1]) == ("revert", 2, 5)

    ok, message = tc.m.restore(scene, records[1]["id"])
    assert ok and message == "Reverted turns 2–5" and reads[-1] == b"before-turn-2"
    del scene.mixie_chat_messages[1:]
    assert _lists(tc, scene) == ([1], [5, 4, 3, 2], True, [])

    # Reapplying turn 4 from there reapplies 2, 3 and 4: the scene after
    # turn 4 is the "before turn 5" snapshot, no tip needed.
    line = tc.m.timeline("sess-1", scene)
    assert tc.m.describe_jump(line, records[3]) == ("reapply", 2, 4)
    ok, message = tc.m.restore(scene, records[3]["id"])
    assert ok and message == "Reapplied turns 2–4" and reads[-1] == b"before-turn-5"
    assert sent[-1][1][-1][1]["request_id"] == "cmd-5"
    for _ in range(3):
        _send(scene)
    assert _lists(tc, scene) == ([4, 3, 2, 1], [5], True, [])
    assert _kinds(tc) == ["tip"] + ["turn"] * 5


def test_hand_edits_on_a_reverted_position_are_kept_as_a_safety_copy(tc, monkeypatch):
    scene = _scene(users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene)
    tc.m.restore(scene, records[2]["id"])
    del scene.mixie_chat_messages[2:]
    assert tc.m.changed_since_arrival("sess-1") is False
    _edit(tc)                                    # moved a cube by hand
    assert tc.m.changed_since_arrival("sess-1") is True
    tc.document["bytes"] = b"turn-2-state-plus-my-edit"

    ok, message = tc.m.restore(scene, records[2]["id"])   # reapply turn 3
    assert ok and message == "Reapplied turn 3. Your edits since are kept as a safety copy"
    safety = tc.m.timeline("sess-1", scene)["safety"]
    assert [s["label"] for s in safety] == ["your edits after turn 2"]
    assert safety[0]["turn_index"] == 2 and safety[0]["request_id"]
    assert open(os.path.join(tc.m.session_dir("sess-1"), safety[0]["file"]), "rb").read() == b"turn-2-state-plus-my-edit"
    assert [m for m, _ in sent[-1][1]] == ["checkpoint.mark", "checkpoint.rewind"]
    _send(scene, "turn 3")

    # Bringing the edits back is a plain jump to that copy; nothing is lost
    # on the way (the tip still holds), so no further record appears.
    line = tc.m.timeline("sess-1", scene)
    assert tc.m.describe_jump(line, safety[0]) == ("bring back", 0, 0)
    ok, message = tc.m.restore(scene, safety[0]["id"])
    assert ok and message == "Brought back your edits" and reads[-1] == b"turn-2-state-plus-my-edit"
    assert _kinds(tc) == ["safety", "tip", "turn", "turn", "turn"]


def test_leaving_the_tip_after_a_hand_edit_replaces_the_stored_tip(tc, monkeypatch):
    scene = _scene(users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene)
    tc.m.restore(scene, records[2]["id"])        # tip stored
    del scene.mixie_chat_messages[2:]
    tc.m.restore(scene, records[2]["id"])        # back on the tip
    _send(scene, "turn 3")
    old_tip = tc.m.timeline("sess-1", scene)["tip"]
    _edit(tc)
    tc.document["bytes"] = b"tip-plus-my-edit"
    ok, message = tc.m.restore(scene, records[2]["id"])
    assert ok and message == "Reverted turn 3"
    tips = [i for i in tc.m.list_checkpoints("sess-1") if i["kind"] == "tip"]
    assert len(tips) == 1 and tips[0]["id"] != old_tip["id"]
    assert not os.path.exists(os.path.join(tc.m.session_dir("sess-1"), old_tip["file"]))
    assert open(os.path.join(tc.m.session_dir("sess-1"), tips[0]["file"]), "rb").read() == b"tip-plus-my-edit"


def test_a_new_message_from_a_reverted_position_drops_the_reverted_turns(tc, monkeypatch):
    scene = _scene(users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene, turns=4)
    tc.m.restore(scene, records[1]["id"])        # revert turns 2–4, tip stored
    del scene.mixie_chat_messages[1:]
    _edit(tc)
    tc.document["bytes"] = b"turn-1-state-plus-edit"
    tc.m.restore(scene, records[0]["id"])        # revert turn 1 too: hand edits kept
    del scene.mixie_chat_messages[:]
    assert _lists(tc, scene) == ([], [4, 3, 2, 1], True, ["your edits after turn 1"])
    tc.m.restore(scene, records[1]["id"])        # reapply turn 1 (before turn 2)
    _send(scene, "turn 1")
    dead = [i for i in tc.m.list_checkpoints("sess-1") if i["kind"] == "tip" or i["turn_index"] > 1]

    # A fresh message from after turn 1 starts a new line: turns 2–4, the
    # tip and any copy from the dead line are gone, files included.
    tc.document["bytes"] = b"before-new-turn-2"
    new_turn = tc.m.capture(scene, "a different turn 2")
    _send(scene, "a different turn 2")
    assert _lists(tc, scene) == ([2, 1], [], False, ["your edits after turn 1"])
    assert new_turn["turn_index"] == 2
    kept_files = {i["file"] for i in tc.m.list_checkpoints("sess-1")}
    for record in dead:
        assert record["id"] not in {i["id"] for i in tc.m.list_checkpoints("sess-1")}
        if record["file"] not in kept_files:
            assert not os.path.exists(os.path.join(tc.m.session_dir("sess-1"), record["file"]))


def test_reapplying_needs_the_stored_state_after_the_turn(tc, monkeypatch):
    scene = _scene(users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene)
    del scene.mixie_chat_messages[2:]            # as if turn 3 were reverted but its tip was lost
    ok, message = tc.m.restore(scene, records[2]["id"])
    assert ok is False and message == "The scene after turn 3 is no longer stored"
    tc.bpy.ops.wm.recover_auto_save.assert_not_called()


def test_a_restart_treats_the_position_as_changed_but_never_loses_state(tc, monkeypatch):
    scene = _scene(users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene)
    tc.m.restore(scene, records[2]["id"])
    del scene.mixie_chat_messages[2:]
    tc.m._arrival.update({"session": "", "stamp": ""})      # process memory gone
    assert tc.m.changed_since_arrival("sess-1") is True
    ok, message = tc.m.restore(scene, records[2]["id"])
    # Conservative: one spare safety copy rather than a lost edit.
    assert ok and message == "Reapplied turn 3. Your edits since are kept as a safety copy"


def test_duplicate_turn_numbers_from_older_builds_resolve_to_the_newest(tc, monkeypatch):
    scene = _scene(users=0)
    records = _turns(tc, scene, 2)
    items = tc.m._load_index("sess-1")
    items.append(dict(records[1], id="older", seq=0, file=records[1]["file"], created_at="2026-01-01T00:00:00+00:00"))
    tc.m._write_index("sess-1", items)
    line = tc.m.timeline("sess-1", scene)
    assert line["by_index"][2]["id"] == records[1]["id"] and len(line["applied"]) == 2


def test_undo_stamp_reads_the_native_operator_and_tolerates_its_absence(tc):
    tc.bpy.context.window_manager.mixie_chat_undo_stamp = "7:0x1:Move"
    assert tc.m.undo_stamp() == "7:0x1:Move"
    tc.bpy.ops.mixie_chat.undo_stamp.assert_called_once_with()
    tc.bpy.ops.mixie_chat.undo_stamp.side_effect = RuntimeError("not registered")
    assert tc.m.undo_stamp() == ""


def test_scene_changes_are_judged_from_the_undo_stack_not_the_depsgraph():
    handlers = (_CHAT_ROOT / "core" / "file_handlers.py").read_text(encoding="utf-8")
    assert "depsgraph_update_post" not in handlers and "note_scene_change" not in handlers
    core = (_CHAT_ROOT / "core" / "turn_checkpoints.py").read_text(encoding="utf-8")
    assert "depsgraph" not in core.split('"""', 2)[2]   # the docstring may explain, the code must not read it
    native = (Path(__file__).parents[2] / "src/source/blender/editors/space_mixie_chat"
              / "mixie_chat_document_ops.cc").read_text(encoding="utf-8")
    assert "MIXIE_CHAT_OT_undo_stamp" in native and "ED_undo_stack_get()" in native
    assert '"mixie_chat_undo_stamp"' in native
    registration = (Path(__file__).parents[2] / "src/source/blender/editors/space_mixie_chat"
                    / "mixie_chat_ops.cc").read_text(encoding="utf-8")
    assert "WM_operatortype_append(MIXIE_CHAT_OT_undo_stamp)" in registration
    props = (_CHAT_ROOT / "ui" / "properties" / "history_props.py").read_text(encoding="utf-8")
    assert "mixie_chat_undo_stamp" in props and "mixie_chat_history_current" not in props
    ops = (_CHAT_ROOT / "ui" / "operators" / "history_ops.py").read_text(encoding="utf-8")
    assert "bpy.types.WindowManager." not in ops        # properties and operators stay in separate folders


def test_native_card_sections_prompts_and_cursor_lock():
    chat = Path(__file__).parents[2] / "src/source/blender/editors/space_mixie_chat"
    events = (chat / "mixie_chat_history_events.cc").read_text(encoding="utf-8")
    cursor = events[events.index("bool mixie_chat_history_cursor("):events.index("static bool history_handle_key(")]
    assert "mixie_chat_history_read_locked(wm)" in cursor
    assert "const bool in_list = !locked &&" in cursor
    arm = events[events.index("static void history_arm_or_restore_row"):events.index("static void history_arm_or_delete_row")]
    assert "read_current" not in arm            # no "already here" row: the lists say what a click does
    targets = (chat / "mixie_chat_qa_targets.cc").read_text(encoding="utf-8")
    assert "t.detail = row.group" in targets and "restored" not in targets
    ops = (_CHAT_ROOT / "ui" / "operators" / "checkpoint_ops.py").read_text(encoding="utf-8")
    assert 'GROUP_REVERTED = "Reverted turns"' in ops and "entry.action = checkpoint_row_action(line, item)" in ops
    assert "mixie_chat_history_current" not in ops


def test_row_prompts_name_the_turns_a_click_moves(tc, monkeypatch):
    ops_path = _CHAT_ROOT / "ui" / "operators" / "checkpoint_ops.py"
    source = ops_path.read_text(encoding="utf-8")
    # Lift the pure helpers out of the operator module (bpy.types.Operator is a mock there).
    helpers = source[source.index("GROUP_TURNS ="):source.index("def sync_checkpoint_entries")]
    namespace = {"turn_checkpoints": tc.m, "format_relative_time": lambda *a, **k: ""}
    exec(helpers, namespace)
    scene = _scene(users=0)
    records = _turns(tc, scene, 5)
    del scene.mixie_chat_messages[2:]            # turns 3–5 reverted
    line = tc.m.timeline("sess-1", scene)
    prompt = namespace["checkpoint_row_action"]
    assert prompt(line, records[1]) == "Revert this turn?"
    assert prompt(line, records[0]) == "Revert turns 1–2?"
    assert prompt(line, records[2]) == "Reapply this turn?"
    assert prompt(line, records[4]) == "Reapply turns 3–5?"
    assert prompt(line, {"kind": "safety", "turn_index": 2}) == "Bring back?"
    assert namespace["checkpoint_row_title"](records[3]) == "Turn 4 · turn 4"
    assert namespace["checkpoint_row_title"]({"kind": "safety", "label": "your edits after turn 2"}) == "Safety copy · your edits after turn 2"


def test_reverting_to_before_turn_1_keeps_the_timeline_reachable(tc, monkeypatch):
    """Before turn 1 predates the backend conversation, so the chat's session
    id is cleared; the checkpoints must not vanish with it."""
    scene = _scene(session_id="", users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene)
    session_id = scene.mixie_session_id
    assert records[0]["session_was_new"] is True
    ok, message = tc.m.restore(scene, records[0]["id"])
    assert ok and message == "Reverted turns 1–3" and reads == [b"before-turn-1"]
    del scene.mixie_chat_messages[:]
    assert scene.mixie_session_id == "" and scene.mixie_checkpoint_session_id == session_id
    assert tc.m.checkpoint_session_id(scene) == session_id
    assert [m for m, _ in sent[-1][1]] == ["checkpoint.mark"]     # the tip, under the old session
    line = tc.m.timeline(tc.m.checkpoint_session_id(scene), scene)
    assert [r["turn_index"] for r in line["reverted"]] == [3, 2, 1] and line["tip"]
    # Reapplying works from that remembered id; the read brings the id back.
    ok, message = tc.m.restore(scene, records[2]["id"])
    assert ok and message == "Reapplied turns 1–3" and reads[-1] == b"tip"
    scene.mixie_session_id = session_id
    for _ in range(3):
        _send(scene)
    assert tc.m.timeline(tc.m.checkpoint_session_id(scene), scene)["reverted"] == []
    # A new message from before turn 1 instead starts a new line: new id, the
    # remembered one forgotten.
    tc.m.restore(scene, records[0]["id"])
    del scene.mixie_chat_messages[:]
    tc.document["bytes"] = b"before-new-turn-1"
    new = tc.m.capture(scene, "a different turn 1")
    assert new["session_id"] != session_id and scene.mixie_checkpoint_session_id == ""
    assert tc.m.checkpoint_session_id(scene) == new["session_id"]


def test_gaps_in_the_turn_numbers_still_reapply_and_name_stored_turns(tc, monkeypatch):
    """A reply or interjection adds a user bubble without a snapshot, so the
    next turn's number skips one."""
    scene = _scene(users=0)
    records = _turns(tc, scene, 2)                # turns 1, 2
    _send(scene, "a reply to a question")         # no capture
    records += _turns(tc, scene, 1, start=3)      # captured with turn_index 4
    assert [r["turn_index"] for r in records] == [1, 2, 4]
    sent = []
    monkeypatch.setattr(tc.m, "_send_backend", lambda sid, calls: sent.append((sid, calls)))
    reads = []

    def recover(filepath=""):
        reads.append(open(filepath, "rb").read())
        tc.bpy.context.window_manager.mixie_chat_undo_stamp = f"read-{len(reads)}"
        return {'FINISHED'}
    tc.bpy.ops.wm.recover_auto_save.side_effect = recover
    tc.bpy.data.scenes = [scene]

    line = tc.m.timeline("sess-1", scene)
    assert line["position"] == 4 and line["max_turn"] == 4
    assert tc.m.describe_jump(line, records[1]) == ("revert", 2, 4)
    ok, message = tc.m.restore(scene, records[1]["id"])       # revert 2 (and 4)
    assert ok and message == "Reverted turns 2–4" and reads[-1] == b"before-turn-2"
    del scene.mixie_chat_messages[1:]
    line = tc.m.timeline("sess-1", scene)
    assert [r["turn_index"] for r in line["reverted"]] == [4, 2]
    assert tc.m.describe_jump(line, records[1]) == ("reapply", 2, 2)
    assert tc.m.describe_jump(line, records[2]) == ("reapply", 2, 4)
    # The state after turn 2 is the next STORED turn's snapshot (before 4).
    ok, message = tc.m.restore(scene, records[1]["id"])
    assert ok and message == "Reapplied turn 2" and reads[-1] == b"before-turn-4"


def test_a_failed_keep_capture_refuses_the_jump(tc, monkeypatch):
    scene = _scene(users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene)
    tc.bpy.ops.wm.save_as_mainfile.side_effect = RuntimeError("disk full")
    ok, message = tc.m.restore(scene, records[2]["id"])
    assert ok is False and message == "Could not keep the current state, so nothing was changed"
    assert reads == [] and sent == []


def test_a_failed_read_drops_the_record_it_had_just_captured(tc, monkeypatch):
    scene = _scene(users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene)
    tc.bpy.ops.wm.recover_auto_save.side_effect = lambda **kw: {'CANCELLED'}
    ok, message = tc.m.restore(scene, records[2]["id"])
    assert ok is False and "Could not read" in message and sent == []
    assert _kinds(tc) == ["turn", "turn", "turn"]              # no orphaned, unmarked tip
    files = {f for f in os.listdir(tc.m.session_dir("sess-1")) if f.endswith(".mixar")}
    assert files == {r["file"] for r in records}


def test_every_read_is_preceded_by_the_bubble_purge(tc, monkeypatch):
    import sys
    purge = sys.modules["mixar.modules.agent_bubble.core.bubble_lifecycle"].close_restored_agent_bubble_windows
    scene = _scene(users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene)
    order = []
    purge.side_effect = lambda: order.append("purge")
    tc.bpy.ops.wm.recover_auto_save.side_effect = lambda filepath="": (order.append("read"), {'FINISHED'})[1]
    tc.m.restore(scene, records[2]["id"])                 # tip captured, then read
    del scene.mixie_chat_messages[2:]
    tc.m.restore(scene, records[2]["id"])                 # nothing to keep: no save, still purged
    assert order == ["purge", "read", "purge", "read"]


def test_hand_edits_after_a_revert_to_before_turn_1_are_filed_under_the_remembered_session(tc, monkeypatch):
    scene = _scene(session_id="", users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene)
    session_id = scene.mixie_session_id
    tc.m.restore(scene, records[0]["id"])            # before turn 1: chat id cleared
    del scene.mixie_chat_messages[:]
    assert scene.mixie_session_id == "" and scene.mixie_checkpoint_session_id == session_id
    _edit(tc)
    tc.document["bytes"] = b"empty-plus-my-edit"
    ok, message = tc.m.restore(scene, records[2]["id"])   # reapply 1–3, edits kept
    assert ok and message.endswith("kept as a safety copy")
    # The copy sits in the remembered session, where the card looks, and
    # the remembered id was not wiped by a minted one.
    assert scene.mixie_checkpoint_session_id == session_id
    line = tc.m.timeline(tc.m.checkpoint_session_id(scene), scene)
    assert [r["label"] for r in line["safety"]] == ["your edits after turn 0"]
    assert os.listdir(tc.m.checkpoints_root()) == [session_id]
    # A copy with no session to belong to is refused rather than misfiled.
    scene.mixie_session_id = ""
    scene.mixie_checkpoint_session_id = ""
    assert tc.m.capture(scene, "stray", kind="safety") is None


def test_the_chats_button_switches_an_open_checkpoints_card_instead_of_closing_it():
    ops = (_CHAT_ROOT / "ui" / "operators" / "history_ops.py").read_text(encoding="utf-8")
    show = ops[ops.index("class MIXIE_CHAT_OT_show_history"):ops.index("class MIXIE_CHAT_OT_open_history_session")]
    assert "opening = not (wm.mixie_chat_history_visible and wm.mixie_chat_history_mode == 'CHATS')" in show
    chat = Path(__file__).parents[2] / "src/source/blender/editors/space_mixie_chat"
    overlay = (chat / "mixie_chat_history_overlay.cc").read_text(encoding="utf-8")
    # Switching modes on the open card resets the search like opening does,
    # and checkpoint rows are never filtered by a leftover chat query.
    assert "rt->history_mode_last != int(mode)" in overlay
    assert "if (checkpoints || rt->history_search[0] == '\\0' ||" in overlay


def test_bringing_back_the_oldest_safety_copy_is_not_evicted_by_the_copy_the_jump_takes(tc, monkeypatch):
    monkeypatch.setattr(tc.m, "MAX_SAFETY_PER_SESSION", 3)
    scene = _scene(users=0)
    records, sent, reads = _prepare_timeline(tc, monkeypatch, scene)
    tc.m.restore(scene, records[1]["id"])                 # revert turns 2–3
    del scene.mixie_chat_messages[1:]
    copies = []
    for i in range(3):                                    # fill the safety cap with hand edits
        _edit(tc, f"edit-{i}")
        tc.document["bytes"] = f"turn-1-plus-edit-{i}".encode()
        tc.m.restore(scene, records[1]["id"])             # reapply 2 (copy taken), then back below
        _send(scene)
        tc.m.restore(scene, records[1]["id"])
        del scene.mixie_chat_messages[1:]
        copies.append(tc.m.timeline("sess-1", scene)["safety"][-1])
    assert [c["label"] for c in tc.m.timeline("sess-1", scene)["safety"]] == ["your edits after turn 1"] * 3
    oldest = sorted(copies, key=lambda r: r["seq"])[0]
    oldest_path = os.path.join(tc.m.session_dir("sess-1"), oldest["file"])
    assert os.path.isfile(oldest_path)
    # One more hand edit, then bring back the OLDEST copy: the copy this jump
    # takes is the fourth, and the cap of three must not evict the target.
    _edit(tc, "edit-final")
    tc.document["bytes"] = b"turn-1-plus-final-edit"
    ok, message = tc.m.restore(scene, oldest["id"])
    assert ok and message == "Brought back your edits. Your edits since are kept as a safety copy"
    assert reads[-1] == b"turn-1-plus-edit-0"
    assert os.path.isfile(oldest_path)
    ids = {r["id"] for r in tc.m.list_checkpoints("sess-1")}
    assert oldest["id"] in ids and len([r for r in tc.m.list_checkpoints("sess-1") if r["kind"] == "safety"]) == 4

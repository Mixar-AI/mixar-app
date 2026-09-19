# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where the scene is on its checkpoint timeline, and what a click does.

The chat holds N-1 user messages before turn N, so the number of user
messages IS the position (``timeline``): turns at or below it are applied,
above it reverted. ``describe_jump`` names what clicking a record does,
``_state_after`` finds the record holding the scene after a turn. Whether
the document changed since the last jump is answered by Blender's undo stack
(``undo_stamp``, ``changed_since_arrival``), never by file bytes or depsgraph
traffic. The document helpers (main window, native re-title, modified
re-tag, bubble purge) live here too; the store and the jump itself are in
``turn_checkpoints``.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _user_message_count(scene) -> int:
    messages = getattr(scene, "mixie_chat_messages", None) or []
    return sum(1 for m in messages if getattr(m, "sender", "") == "USER")


def _main_window():
    """The document's main window. The chat island lives in a temporary
    companion window that a file read tears down, so the read and the save
    run with the main window as context whichever window asked."""
    import bpy
    try:
        for window in bpy.context.window_manager.windows:
            screen = getattr(window, "screen", None)
            if screen is not None and not getattr(screen, "is_temporary", False):
                return window
    except Exception:  # noqa: BLE001
        pass
    return bpy.context.window


def _retitle(filepath: str):
    """Native re-title of the open document (no write); safe to repeat."""
    import bpy
    try:
        with bpy.context.temp_override(window=_main_window()):
            bpy.ops.mixie_chat.retitle_document(filepath=filepath)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Turn checkpoint: could not re-title the restored document: {e}", exc_info=True)
    return None  # timer callback: never reschedule


def _keep_modified(filepath: str, ticks: int = 10):
    """Timer body: re-title (and so re-tag modified) until the modified flag
    survives two consecutive ticks; bounded so it can never run forever."""
    import bpy
    state = {"left": ticks, "held": 0}

    def tick():
        if bpy.data.is_dirty:
            state["held"] += 1
        else:
            state["held"] = 0
            _retitle(filepath)
        state["left"] -= 1
        return None if state["held"] >= 2 or state["left"] <= 0 else 0.05
    return tick


# Where the last jump landed (this process): the undo stamp taken right after
# the read. While it still matches, nothing has been done to the document
# since, so the state on the reverted position is exactly the snapshot it
# came from and needs no copy. A missing or stale stamp is treated as
# "changed": the only cost is a spare safety copy.
_arrival = {"session": "", "stamp": ""}


def undo_stamp() -> str:
    """Fingerprint of Blender's undo stack (step count, active step), read
    natively by ``mixie_chat.undo_stamp``. A file read resets the stack;
    interactive operators, UI property edits and scripts that push a step
    move it; the chat's own property writes and the re-title do not."""
    try:
        import bpy
        with bpy.context.temp_override(window=_main_window()):
            bpy.ops.mixie_chat.undo_stamp()
        return str(bpy.context.window_manager.mixie_chat_undo_stamp or "")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"undo stamp unavailable: {e}")
        return ""


def _note_arrival(session_id: str) -> None:
    _arrival["session"] = session_id
    _arrival["stamp"] = undo_stamp()


def changed_since_arrival(session_id: str) -> bool:
    """True unless the document is known to be untouched since the last jump."""
    if not session_id or _arrival.get("session") != session_id or not _arrival.get("stamp"):
        return True
    return undo_stamp() != _arrival["stamp"]


def checkpoint_session_id(scene) -> str:
    """The session whose checkpoints belong to this scene: the chat's session
    id, or the one remembered when a revert to before turn 1 cleared it."""
    if scene is None:
        return ""
    return (getattr(scene, "mixie_session_id", "") or ""
            or getattr(scene, "mixie_checkpoint_session_id", "") or "")


def timeline(session_id: str, scene) -> dict:
    """The session's turns split around where the scene is.

    ``position`` is the chat's user-message count (the snapshot before turn N
    holds N-1). ``applied`` are the turns at or below it, ``reverted`` the
    ones above it whose state after them is still stored, both newest first;
    ``by_index`` maps turn number to its "before" record (the newest wins if
    an older build left duplicates); ``tip`` is the state after the highest
    turn, if a revert stored it; ``safety`` are the hand-edit copies.

    Turn numbers are the user-message count at capture plus one, so a reply
    or an interjection that adds a user bubble without a snapshot leaves a
    gap in the numbering; the position rule holds regardless."""
    from .turn_checkpoints import list_checkpoints  # the store; imported lazily (it imports this module)
    items = list_checkpoints(session_id)
    by_index = {}
    for record in items:  # newest first
        if record.get("kind", "turn") == "turn":
            by_index.setdefault(int(record.get("turn_index", 0) or 0), record)
    turns = [by_index[i] for i in sorted(by_index, reverse=True)]
    position = _user_message_count(scene)
    line = {
        "position": position,
        "max_turn": max(by_index, default=0),
        "by_index": by_index,
        "applied": [r for r in turns if int(r["turn_index"]) <= position],
        "tip": next((r for r in items if r.get("kind") == "tip"), None),
        "safety": [r for r in items if r.get("kind") == "safety"],
    }
    line["reverted"] = [r for r in turns if int(r["turn_index"]) > position
                        and _state_after(line, int(r["turn_index"])) is not None]
    return line


def _state_after(line: dict, turn: int):
    """The record holding the scene after ``turn``: the next stored turn's
    "before" snapshot, or the tip for the last turn. None when it is not
    stored (pruned, or an older build never kept it)."""
    later = [i for i in line["by_index"] if i > turn]
    if later:
        return line["by_index"].get(min(later))
    if turn == line["max_turn"]:
        return line["tip"]
    return None


def describe_jump(line: dict, record: dict) -> tuple:
    """What clicking ``record`` does, as ``(verb, first, last)``: "revert"
    turns first..last, "reapply" turns first..last (existing turn numbers),
    or "bring back" for a safety copy (first == last == 0)."""
    position = int(line["position"] or 0)
    n = int(record.get("turn_index", 0) or 0)
    if record.get("kind", "turn") != "turn":
        return "bring back", 0, 0
    if n <= position:
        applied = [i for i in line["by_index"] if i <= position]
        return "revert", n, max(applied, default=n)
    reverted = [i for i in line["by_index"] if position < i <= n]
    return "reapply", min(reverted, default=n), n


def _jump_message(verb: str, first: int, last: int) -> str:
    if verb == "bring back":
        return "Brought back your edits"
    head = "Reverted" if verb == "revert" else "Reapplied"
    return f"{head} turn {first}" if first == last else f"{head} turns {first}–{last}"

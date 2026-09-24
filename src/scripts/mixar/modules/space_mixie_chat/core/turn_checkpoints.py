# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn checkpoints: one timeline of turns per chat, revert and reapply.

Capture (``capture``): right before a fresh message goes out, the whole
document is written with ``save_as_mainfile(copy=True)`` to
``~/.mixar/checkpoints/<session>/<id>.mixar`` as the ``turn`` record "before
turn N". Chat bubbles and the session id live in scene properties, so the
file already holds the conversation as it was at that moment. Identical
bytes are stored once (sha256), and only the newest ``MAX_PER_SESSION``
turns of a session are kept.

Where the scene is (``timeline``): the chat holds N-1 user messages before
turn N, so the number of user messages IS the position. Turns at or below
it are applied, turns above it are reverted. Nothing else is stored to know
this, which is why a restart or a reopened file cannot get it wrong.

Restore (``restore``): reverting turn N puts the document back to the
"before turn N" snapshot; every later turn is reverted with it. Reapplying
a reverted turn N puts it at the state after N, which is the "before turn
N+1" snapshot, or for the last turn the ``tip`` record captured when it was
reverted. The same row therefore alternates between the two lists instead
of minting copies. Only a state that would otherwise be lost is captured
before a jump: the tip when leaving it, and hand edits made on a reverted
position (a ``safety`` record, "your edits after turn K"), judged from
Blender's undo stack (``undo_stamp``), never from file bytes or depsgraph
traffic. The stack sees what pushes an undo step: interactive operators and
UI property edits, and scripts that push one. A Python script writing
``bpy.data`` directly on a reverted position is invisible to it, and a UI
edit of a scene-owned chat property counts as a change; the cost of either
is one full snapshot too few or too many, bounded by the caps. A new message
from a reverted position drops the reverted turns.

Reverting to before turn 1 predates the backend conversation, so the chat's
session id is cleared for the next message; the scene keeps the id under
``mixie_checkpoint_session_id`` so the card still lists the timeline
(``checkpoint_session_id``) and the turns can be reapplied.

The snapshot is read back with ``wm.recover_auto_save``. A copy carries no
recovery header, so the read leaves the document untitled; the native
``mixie_chat.retitle_document`` operator gives it the recorded original path
back in memory and marks it modified. Nothing is ever written to the
artist's project: a titled project is dirty on its own path until they
choose to save, and a project that was untitled stays untitled so Ctrl-S
opens Save As. Snapshots are written with ``relative_remap=False`` so
relative paths still resolve against the project's own folder.

The conversation half lives on the backend: the snapshot taken before turn
N is bound to that turn's command id (``bind_request``), and after a jump
``checkpoint.rewind`` asks the backend to fork the session thread from
there. Tip and safety records get their own bookmark through
``checkpoint.mark``. Both go over the agent socket on a worker thread; the
composer refuses to send while they are in flight
(``rewind_in_flight``). See ``docs/api/frontend/turn-checkpoints.md`` in
mixar-backend.
"""

import os
import time
import uuid

from mixar.config.logging_config import get_logger

from ..constants import DEV_MODE, SessionState
from . import checkpoint_backend, checkpoint_budget, checkpoint_store  # noqa: F401 — tests patch through them
from .checkpoint_backend import (  # noqa: F401 — re-exported for callers and tests
    _clear_session_on_main, _notify, _send_backend, _session_scene, rewind_in_flight,
)
from .checkpoint_timeline import (  # noqa: F401 — re-exported for callers and tests
    _arrival, _jump_message, _keep_modified, _main_window, _note_arrival, _retitle,
    _state_after, _user_message_count, changed_since_arrival, checkpoint_session_id,
    describe_jump, timeline, undo_stamp,
)
from .checkpoint_store import (  # noqa: F401 — re-exported for callers and tests
    _atomic_write_json, _file_path, _has_cache, _index_path, _load_index, _order,
    _now_iso, _read_json, _remove_files, _safe_id, _sha256, _update, _write_index,
    checkpoints_root, get_checkpoint, has_checkpoints, list_checkpoints, session_dir,
)

logger = get_logger(__name__)

MAX_PER_SESSION = 20          # turn snapshots kept per session
MAX_SAFETY_PER_SESSION = 10   # hand-edit copies, pruned only among themselves
# Per-session pruning alone is not a disk budget: it bounds one chat at 20
# snapshots, but nothing ever retired a session DIRECTORY, and each snapshot is
# a full copy of the document. Left to run, a few dozen chats multiply into tens
# of gigabytes in a hidden folder the user never sees.
#
# Same shape as operation_history's cleanup: an age cutoff, a once-a-day guard,
# and rmtree of whatever falls outside it.
MAX_AGE_DAYS = 15
MAX_SESSIONS = 40          # newest session dirs kept, whatever their age
_LABEL_LIMIT = 80

_restoring = False


def _prune(session_id: str, items: list, protect_id: str = "") -> list:
    """Keep the newest records per kind (turns, one tip, safety copies)."""
    return checkpoint_store.prune(items, max_turns=MAX_PER_SESSION, max_safety=MAX_SAFETY_PER_SESSION,
                                  protect_id=protect_id)


_last_cleanup_day = -1


def prune_sessions(keep_session_id: str = "") -> int:
    """Retire stale session directories (see ``checkpoint_budget``); the live
    session is never a candidate."""
    keep = _safe_id(keep_session_id) if keep_session_id else ""
    return checkpoint_budget.prune_sessions(checkpoints_root(), keep,
                                            max_age_days=MAX_AGE_DAYS, max_sessions=MAX_SESSIONS)


def _prune_sessions_once_per_day(keep_session_id: str = "") -> None:
    global _last_cleanup_day
    day = int(time.time() // 86400)
    if _last_cleanup_day == day:
        return
    _last_cleanup_day = day
    try:
        prune_sessions(keep_session_id)
    except Exception as e:  # noqa: BLE001 — housekeeping never blocks a capture
        logger.warning(f"Turn checkpoint session prune skipped: {e}")


# =============================================================================
# Capture
# =============================================================================

def capture(scene, label: str, *, kind: str = "turn", session_id: str = "", protect_id: str = ""):
    """Snapshot the whole document. Returns the record, or None when nothing
    was written. Never raises: a checkpoint must not stop a send.

    A turn snapshot is filed under the chat's session; a chat with no session
    id yet gets one here (``start_session`` keeps an existing id), and
    ``session_was_new`` remembers that the backend has no conversation for
    it — a restore then clears the id instead of asking for a rewind. A tip
    or safety record passes the timeline's ``session_id`` explicitly: after a
    revert to before turn 1 the chat's id is empty while the timeline still
    lives under the remembered one, and a copy minted into a fresh session
    would never show on the card. ``protect_id`` is a record the caller is
    about to read: the prune this capture triggers must not evict it.
    """
    if DEV_MODE or scene is None:
        return None
    try:
        import bpy

        if not session_id:
            # A turn is filed under the chat's session (a new chat mints one
            # below); a tip or safety copy belongs to the timeline the scene
            # is on, which outlives a cleared chat id.
            session_id = (getattr(scene, "mixie_session_id", "") or "") if kind == "turn" \
                else checkpoint_session_id(scene)
        session_was_new = not session_id
        if session_was_new and kind != "turn":
            logger.warning("Turn checkpoint: no session to file a %s copy under", kind)
            return None
        if session_was_new:
            session_id = str(uuid.uuid4())
            scene.mixie_session_id = session_id
            if hasattr(scene, "mixie_checkpoint_session_id"):
                scene.mixie_checkpoint_session_id = ""   # a new line, in a new directory

        directory = session_dir(session_id)
        checkpoint_id = uuid.uuid4().hex[:12]
        tmp = os.path.join(directory, f"{checkpoint_id}.tmp.mixar")
        # relative_remap=False: the snapshot keeps paths relative to the
        # project's own folder, which is where a restore re-titles it. The
        # Agent Bubble's save_pre purge closes the island for this save like
        # any other; it is re-shown after the save.
        # A document with Automatically Pack Resources on packs every image
        # during this save, and each image whose file is missing on disk
        # ("Unable to pack file ... not found", e.g. an FBX whose textures
        # stayed on another machine) is an RPT_ERROR that bpy.ops turns into
        # RuntimeError after the file was still written. The snapshot on
        # disk is the truth: keep it, only give up when nothing was saved.
        try:
            bpy.ops.wm.save_as_mainfile(filepath=tmp, copy=True, compress=True,
                                        relative_remap=False)
        except RuntimeError as e:
            if not os.path.isfile(tmp):
                raise
            logger.warning(f"Turn checkpoint saved with report errors: {e}")
        if not os.path.isfile(tmp):
            logger.warning("Turn checkpoint: nothing written")
            return None

        digest = _sha256(tmp)
        size = os.path.getsize(tmp)
        items = _load_index(session_id)
        position = _user_message_count(scene)
        if kind == "turn":
            # A message sent from a reverted position starts a new line of
            # turns: the reverted ones (and the tip they led to) can never
            # come back into a list that now has different turns at their
            # numbers, so they are dropped. Hand-edit copies from that dead
            # line go with them.
            dropped = [i for i in items if i.get("kind") == "tip"
                       or int(i.get("turn_index", 0) or 0) > position]
        elif kind == "tip":
            dropped = [i for i in items if i.get("kind") == "tip"]  # one tip at a time
        else:
            dropped = []
        items = [i for i in items if i not in dropped]
        same = next((i for i in items if i.get("sha256") == digest and os.path.isfile(_file_path(i))), None)
        if same is not None:
            os.remove(tmp)
            filename = same["file"]
        else:
            filename = f"{checkpoint_id}.mixar"
            checkpoint_store.replace_file(tmp, os.path.join(directory, filename))
        record = {
            "id": checkpoint_id,
            "seq": max((int(i.get("seq", 0) or 0) for i in items), default=0) + 1,
            "session_id": session_id,
            "kind": kind,
            "request_id": "",
            "turn_index": position + (1 if kind == "turn" else 0),
            "label": (label or "").strip().replace("\n", " ")[:_LABEL_LIMIT],
            "created_at": _now_iso(),
            "file": filename,
            "sha256": digest,
            "bytes": size,
            "original_path": bpy.data.filepath or "",
            "session_was_new": session_was_new,
            "message_count": len(getattr(scene, "mixie_chat_messages", None) or []),
        }
        items.append(record)
        _remove_files(dropped, items)
        _write_index(session_id, _prune(session_id, items, protect_id))
        _prune_sessions_once_per_day(session_id)
        logger.info(f"Turn checkpoint {checkpoint_id} written ({size} bytes, turn {record['turn_index']})")
        return record
    except Exception as e:  # noqa: BLE001 — never block the message
        logger.warning(f"Turn checkpoint skipped: {e}", exc_info=True)
        return None


def bind_request(record: dict, request_id: str) -> None:
    """Attach the turn's command id — the backend's request id — to its checkpoint."""
    if not record or not request_id:
        return
    try:
        record["request_id"] = request_id
        _update(record["session_id"], record["id"], request_id=request_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Turn checkpoint bind skipped: {e}")


# =============================================================================
# Restore
# =============================================================================

def is_restoring() -> bool:
    """True while the snapshot is being read; ``load_pre`` must not abort the session."""
    return _restoring


def can_restore(scene):
    """Only an idle, connected session with no open run may swap the document."""
    from .session import get_session_manager
    session = get_session_manager()
    if rewind_in_flight():
        return False, "Restoring a checkpoint…"
    if session.get_state(scene) != SessionState.IDLE:
        return False, "Wait for the agent to finish"
    if session.run_open(scene):
        return False, "The agent is still building"
    return True, ""


def _keep_leaving_state(scene, session_id: str, line: dict, target_id: str = ""):
    """Capture what the jump would lose. Returns ``(kind, record, request_id)``:
    the new record ("tip" or "safety") and the bookmark id to send, ``("",
    None, "")`` when nothing needed keeping, or ``("failed", None, "")`` when
    the capture did not happen (the jump must not proceed: the state would
    be lost)."""
    position = int(line["position"] or 0)
    changed = changed_since_arrival(session_id)
    if position >= line["max_turn"]:
        # Leaving the tip: the state after the last turn exists nowhere else.
        # A tip stored by an earlier revert still holds if nothing has been
        # done since the scene was put back on it.
        if line["tip"] is not None and not changed:
            return "", None, ""
        record = capture(scene, f"after turn {line['max_turn']}", kind="tip",
                         session_id=session_id, protect_id=target_id)
    else:
        if not changed:
            return "", None, ""
        record = capture(scene, f"your edits after turn {position}", kind="safety",
                         session_id=session_id, protect_id=target_id)
    if record is None:
        return "failed", None, ""
    request_id = str(uuid.uuid4())
    bind_request(record, request_id)
    return record["kind"], record, request_id


def _drop_record(session_id: str, record: dict) -> None:
    """Forget a record that never became reachable (its jump did not happen)."""
    try:
        items = [i for i in _load_index(session_id) if i.get("id") != record.get("id")]
        _remove_files([record], items)
        _write_index(session_id, items)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Turn checkpoint: could not drop {record.get('id')}: {e}")


def _close_bubble_windows() -> None:
    """A file read must never find a live Agent Bubble window (their regions
    are freed from the outgoing Main and the motion region free crashes).
    Every save closes them through ``save_pre``, but a jump that has nothing
    to keep saves nothing first, so close them here regardless."""
    try:
        from mixar.modules.agent_bubble.core.bubble_lifecycle import close_restored_agent_bubble_windows
        close_restored_agent_bubble_windows()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Turn checkpoint: bubble purge before the read skipped: {e}")


def restore(scene, checkpoint_id: str):
    """Revert to, reapply through, or bring back ``checkpoint_id``.
    Returns ``(ok, message)``."""
    import bpy
    global _restoring

    session_id = checkpoint_session_id(scene)
    record = get_checkpoint(session_id, checkpoint_id)
    if record is None:
        return False, "Checkpoint not found"
    allowed, reason = can_restore(scene)
    if not allowed:
        return False, reason

    line = timeline(session_id, scene)
    verb, first, last = describe_jump(line, record)
    target = _state_after(line, last) if verb == "reapply" else record
    if target is None or not os.path.isfile(_file_path(target)):
        if verb == "reapply":
            return False, f"The scene after turn {last} is no longer stored"
        return False, "Checkpoint file is missing"

    kept, kept_record, mark_request_id = _keep_leaving_state(scene, session_id, line, target["id"])
    if kept == "failed":
        return False, "Could not keep the current state, so nothing was changed"
    if not os.path.isfile(_file_path(target)):
        # Never expected (the keep-capture protects the target from its own
        # prune), but a read of a missing file must not be attempted.
        if kept_record is not None:
            _drop_record(session_id, kept_record)
        return False, "Checkpoint file is missing"

    original_path = bpy.data.filepath or target.get("original_path") or ""
    window = _main_window()
    _close_bubble_windows()
    _restoring = True
    read_ok = False
    try:
        with bpy.context.temp_override(window=window):
            result = bpy.ops.wm.recover_auto_save(filepath=_file_path(target))
        read_ok = 'FINISHED' in result
    except Exception as e:  # noqa: BLE001
        logger.error(f"Turn checkpoint restore failed: {e}", exc_info=True)
    finally:
        _restoring = False
    if not read_ok:
        # The document is unchanged, so the record captured for this jump
        # holds nothing the timeline needs (and its bookmark was never sent).
        if kept_record is not None:
            _drop_record(session_id, kept_record)
        return False, "Could not read the checkpoint"

    # The read left the document untitled. Give a titled project its own path
    # back IN MEMORY and mark it modified; nothing is written. Saving the
    # restored state over the project is the artist's explicit choice, and an
    # untitled project stays untitled so Ctrl-S opens Save As.
    _retitle(original_path)
    # The read queued Blender's file-read notifier, and processing it (after
    # this operator returns, in the next notifier pass) marks the document
    # saved again. A zero-interval timer still runs before that pass, so keep
    # re-tagging on a short timer until the flag has held across two ticks.
    bpy.app.timers.register(_keep_modified(original_path), first_interval=0.05)

    _note_arrival(target.get("session_id", session_id))
    restored_scene = _session_scene(target.get("session_id", ""))
    _after_load(restored_scene, target, mark_request_id)
    message = _jump_message(verb, first, last)
    if kept == "safety":
        message += ". Your edits since are kept as a safety copy"
    return True, message


def restore_deferred(scene_name: str, checkpoint_id: str) -> None:
    """Restore on the next main-loop tick, outside the calling operator.

    The island header button runs its operator inside the companion window;
    the file read closes that window, so the swap must not run on its call
    stack. Failures are reported as a chat notice (no operator to report to)."""
    import bpy

    def _run():
        try:
            scene = bpy.data.scenes.get(scene_name) or _session_scene("")
            ok, message = restore(scene, checkpoint_id)
            if not ok:
                _notify(scene_name, f"Checkpoint not restored: {message}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Deferred checkpoint restore failed: {e}", exc_info=True)
            _notify(scene_name, "Checkpoint not restored: unexpected error")
        return None

    bpy.app.timers.register(_run, first_interval=0.05)


def _after_load(scene, record: dict, mark_request_id: str) -> None:
    """Rebind the live session to the restored transcript and rewind the backend."""
    from .session import get_session_manager
    from .turn_events import drop_scene
    from .ui_utils import bump_layout_epoch, redraw_chat_areas

    session = get_session_manager()
    session.set_run(scene, "", False)
    if session.is_connected(scene):
        session.clear_streaming()
        session.set_connected(scene)
    # Fence the session's turn bookkeeping: the turns newer than the
    # snapshot are complete as far as this transcript is concerned, and the
    # reconnect-time recovery check must not replay them into the restored
    # chat. The next send (``turn_events.expect``) lifts the fence.
    try:
        drop_scene(scene.name)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"turn fence after restore skipped: {e}")
    try:
        from .markdown_parser import clear_incremental_cache
        clear_incremental_cache()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"markdown cache clear after restore skipped: {e}")
    if hasattr(scene, "mixie_chat_user_has_engaged"):
        scene.mixie_chat_user_has_engaged = bool(_user_message_count(scene))
    bump_layout_epoch(scene)
    redraw_chat_areas()

    session_id = record.get("session_id", "")
    if record.get("session_was_new"):
        # The snapshot predates the conversation: the next message starts a
        # new backend session. The checkpoints still belong to the old one,
        # and the card must keep listing them so the turns can be reapplied.
        if hasattr(scene, "mixie_checkpoint_session_id"):
            scene.mixie_checkpoint_session_id = session_id
        session.clear_session_id(scene)
        if mark_request_id:
            _send_backend(session_id, [("checkpoint.mark", {"session_id": session_id, "request_id": mark_request_id})])
        return
    calls = []
    if mark_request_id:
        calls.append(("checkpoint.mark", {"session_id": session_id, "request_id": mark_request_id}))
    if record.get("request_id"):
        calls.append(("checkpoint.rewind", {"session_id": session_id, "request_id": record["request_id"]}))
    else:
        _notify(scene.name, "Scene restored. This checkpoint has no conversation bookmark, so the chat memory was not rewound.")
    _send_backend(session_id, calls)

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn checkpoints: a ``.mixar`` snapshot before every fresh turn, and a
one-click way back to it while the session is idle.

Capture (``capture``): right before a fresh message goes out, the whole
document is written with ``save_as_mainfile(copy=True)`` to
``~/.mixar/checkpoints/<session>/<id>.mixar``. Chat bubbles and the session
id live in scene properties, so the file already holds the conversation as
it was at that moment. Identical bytes are stored once (sha256), and only
the newest ``MAX_PER_SESSION`` checkpoints of a session are kept.

Restore (``restore``): a safety copy of the current state is captured first,
then the snapshot is read back with ``wm.recover_auto_save``. Nothing on disk
is touched by the read, but the recovered document's path becomes the
snapshot file (a copy carries no recovery header for Blender to take the
original path from), and no operator can make a document untitled again. So
the document is always saved once right after the read: a project that had a
path goes back to it (the one place this module writes the user's file); a
project that was untitled goes to the session's ``working.mixar`` next to
its checkpoints, so a later Ctrl-S can never overwrite a checkpoint.

The conversation half lives on the backend: the snapshot taken before turn
N is bound to that turn's command id (``bind_request``), and after a restore
``checkpoint.rewind`` asks the backend to fork the session thread from
where that turn started. The safety copy gets its own bookmark through
``checkpoint.mark``. Both go over the agent socket on a worker thread; the
composer refuses to send while they are in flight
(``rewind_in_flight``). See ``docs/api/frontend/turn-checkpoints.md`` in
mixar-backend.
"""

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone

from mixar.config.logging_config import get_logger

from ..constants import DEV_MODE, SessionState

logger = get_logger(__name__)

MAX_PER_SESSION = 20
# Per-session pruning alone is not a disk budget: it bounds one chat at 20
# snapshots, but nothing ever retired a session DIRECTORY, and each snapshot is
# a full copy of the document. Left to run, a few dozen chats multiply into tens
# of gigabytes in a hidden folder the user never sees. `working.mixar` is not in
# any index either, so it was never reclaimed at all.
#
# Same shape as operation_history's cleanup: an age cutoff, a once-a-day guard,
# and rmtree of whatever falls outside it.
MAX_AGE_DAYS = 15
MAX_SESSIONS = 40          # newest session dirs kept, whatever their age
_INDEX_FILENAME = "index.json"
_RECORD_VERSION = 1
_LABEL_LIMIT = 80

_restoring = False
_rewind_inflight = False
_LOCK = threading.Lock()


# =============================================================================
# Paths and JSON
# =============================================================================

def checkpoints_root() -> str:
    """Per-user app-data dir, next to chat_history — never Blender's session
    temp dir, which is purged on exit."""
    return os.path.join(os.path.expanduser("~"), ".mixar", "checkpoints")


def _safe_id(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "")[:80] or "_nosession"


def session_dir(session_id: str) -> str:
    path = os.path.join(checkpoints_root(), _safe_id(session_id))
    os.makedirs(path, exist_ok=True)
    return path


def _index_path(session_id: str) -> str:
    return os.path.join(session_dir(session_id), _INDEX_FILENAME)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _order(item: dict):
    """Newest last: creation time, then the per-session sequence (several
    captures can share a timestamp)."""
    return (item.get("created_at", ""), int(item.get("seq", 0) or 0))


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _atomic_write_json(path: str, data) -> None:
    """tmp + rename so a crash never leaves a half-written index."""
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# =============================================================================
# Index
# =============================================================================

def _load_index(session_id: str) -> list:
    data = _read_json(_index_path(session_id))
    items = data.get("checkpoints") if isinstance(data, dict) else None
    return [i for i in (items or []) if isinstance(i, dict) and i.get("id")]


def _write_index(session_id: str, items: list) -> None:
    _atomic_write_json(_index_path(session_id), {"version": _RECORD_VERSION, "checkpoints": items})


def _file_path(record: dict) -> str:
    return os.path.join(session_dir(record.get("session_id", "")), record.get("file", ""))


WORKING_FILENAME = "working.mixar"


def working_file(session_id: str) -> str:
    """Where a restored UNTITLED project lands: never a checkpoint file."""
    return os.path.join(session_dir(session_id), WORKING_FILENAME)


def list_checkpoints(session_id: str) -> list:
    """Restorable checkpoints of a session, newest first."""
    if not session_id:
        return []
    items = [i for i in _load_index(session_id) if os.path.isfile(_file_path(i))]
    return sorted(items, key=_order, reverse=True)


_has_cache = {}


def has_checkpoints(session_id: str) -> bool:
    """Header-draw cheap: one stat of the index per draw, re-read on change."""
    if not session_id:
        return False
    path = os.path.join(checkpoints_root(), _safe_id(session_id), _INDEX_FILENAME)
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        _has_cache.pop(session_id, None)
        return False
    cached = _has_cache.get(session_id)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    value = bool(list_checkpoints(session_id))
    _has_cache[session_id] = (stamp, value)
    return value


def get_checkpoint(session_id: str, checkpoint_id: str):
    for item in _load_index(session_id):
        if item.get("id") == checkpoint_id:
            return item
    return None


def _prune(session_id: str, items: list) -> list:
    """Keep the newest MAX_PER_SESSION records; drop files nothing references."""
    items = sorted(items, key=_order)
    kept = items[-MAX_PER_SESSION:]
    referenced = {i.get("file") for i in kept}
    for stale in items[:-MAX_PER_SESSION]:
        if stale.get("file") in referenced:
            continue
        try:
            os.remove(_file_path(stale))
        except OSError:
            pass
    return kept


_last_cleanup_day = -1


def _session_mtime(path: str) -> float:
    """Newest mtime in the directory: an active session keeps being written."""
    newest = 0.0
    try:
        newest = os.path.getmtime(path)
        for name in os.listdir(path):
            try:
                newest = max(newest, os.path.getmtime(os.path.join(path, name)))
            except OSError:
                continue
    except OSError:
        pass
    return newest


def _live_document_dir(root: str) -> str:
    """The session directory holding the OPEN document, if it lives under root.

    `restore()` parks a restored UNTITLED project at <session>/working.mixar and
    that becomes bpy.data.filepath -- but the session id that named the directory
    is cleared on that same path, so `keep_session_id` stops protecting it. The
    directory would then be retired by the age cutoff or the count cap, taking
    the user's open document with it. Protect it by where the document actually
    is, not by which session id happens to be current."""
    try:
        import bpy
        path = bpy.data.filepath or ""
        if not path:
            return ""
        parent = os.path.dirname(os.path.abspath(path))
        if os.path.normcase(os.path.dirname(parent)) != os.path.normcase(os.path.abspath(root)):
            return ""
        return os.path.basename(parent)
    except Exception:  # noqa: BLE001 -- housekeeping never blocks a capture
        return ""


def prune_sessions(keep_session_id: str = "") -> int:
    """Retire whole session directories: older than MAX_AGE_DAYS, or outside
    the newest MAX_SESSIONS. The live session is never a candidate. Returns
    how many were removed. Best effort — never raises into a capture."""
    root = checkpoints_root()
    keep = _safe_id(keep_session_id) if keep_session_id else ""
    try:
        names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    except OSError:
        return 0
    protected = {n for n in (keep, _live_document_dir(root)) if n}
    aged = sorted(
        ((n, _session_mtime(os.path.join(root, n))) for n in names if n not in protected),
        key=lambda pair: pair[1], reverse=True,
    )
    cutoff = time.time() - MAX_AGE_DAYS * 86400.0
    # A protected session occupies a slot only once it actually has a directory --
    # reserving one for a session that has not written yet would retire an extra
    # candidate for nothing.
    budget = max(0, MAX_SESSIONS - len(protected & set(names)))
    removed = 0
    for index, (name, mtime) in enumerate(aged):
        if index < budget and mtime >= cutoff:
            continue
        shutil.rmtree(os.path.join(root, name), ignore_errors=True)
        removed += 1
    if removed:
        logger.info(f"Turn checkpoints: retired {removed} stale session director"
                    f"{'y' if removed == 1 else 'ies'}")
    return removed


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


def _update(session_id: str, checkpoint_id: str, **changes) -> None:
    items = _load_index(session_id)
    for item in items:
        if item.get("id") == checkpoint_id:
            item.update(changes)
    _write_index(session_id, items)


# =============================================================================
# Capture
# =============================================================================

def _user_message_count(scene) -> int:
    messages = getattr(scene, "mixie_chat_messages", None) or []
    return sum(1 for m in messages if getattr(m, "sender", "") == "USER")


def capture(scene, label: str, *, kind: str = "turn"):
    """Snapshot the whole document. Returns the record, or None when nothing
    was written. Never raises: a checkpoint must not stop a send.

    A chat with no session id yet gets one here (``start_session`` keeps an
    existing id), so the snapshot is filed under the session it will belong
    to; ``session_was_new`` remembers that the backend has no conversation
    for it — a restore then clears the id instead of asking for a rewind.
    """
    if DEV_MODE or scene is None:
        return None
    try:
        import bpy

        session_id = getattr(scene, "mixie_session_id", "") or ""
        session_was_new = not session_id
        if session_was_new:
            session_id = str(uuid.uuid4())
            scene.mixie_session_id = session_id

        directory = session_dir(session_id)
        checkpoint_id = uuid.uuid4().hex[:12]
        tmp = os.path.join(directory, f"{checkpoint_id}.tmp.mixar")
        bpy.ops.wm.save_as_mainfile(filepath=tmp, copy=True, compress=True)
        if not os.path.isfile(tmp):
            logger.warning("Turn checkpoint: nothing written")
            return None

        digest = _sha256(tmp)
        size = os.path.getsize(tmp)
        items = _load_index(session_id)
        same = next((i for i in items if i.get("sha256") == digest and os.path.isfile(_file_path(i))), None)
        if same is not None:
            os.remove(tmp)
            filename = same["file"]
        else:
            filename = f"{checkpoint_id}.mixar"
            os.replace(tmp, os.path.join(directory, filename))

        record = {
            "id": checkpoint_id,
            "seq": max((int(i.get("seq", 0) or 0) for i in items), default=0) + 1,
            "session_id": session_id,
            "kind": kind,
            "request_id": "",
            "turn_index": _user_message_count(scene) + (1 if kind == "turn" else 0),
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
        _write_index(session_id, _prune(session_id, items))
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


def rewind_in_flight() -> bool:
    return _rewind_inflight


def can_restore(scene):
    """Only an idle, connected session with no open run may swap the document."""
    from .session import get_session_manager
    session = get_session_manager()
    if _rewind_inflight:
        return False, "Restoring a checkpoint…"
    if session.get_state(scene) != SessionState.IDLE:
        return False, "Wait for the agent to finish"
    if session.run_open(scene):
        return False, "The agent is still building"
    return True, ""


def _session_scene(session_id: str):
    import bpy
    for scene in bpy.data.scenes:
        if getattr(scene, "mixie_session_id", "") == session_id:
            return scene
    return bpy.context.window.scene if bpy.context.window else bpy.context.scene


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


def restore(scene, checkpoint_id: str):
    """Put the document back to a checkpoint. Returns ``(ok, message)``."""
    import bpy
    global _restoring

    session_id = getattr(scene, "mixie_session_id", "") or ""
    record = get_checkpoint(session_id, checkpoint_id)
    if record is None:
        return False, "Checkpoint not found"
    path = _file_path(record)
    if not os.path.isfile(path):
        return False, "Checkpoint file is missing"
    allowed, reason = can_restore(scene)
    if not allowed:
        return False, reason

    # Safety copy of what is about to be replaced, restorable like any turn.
    safety = capture(scene, f"Before restoring turn {record.get('turn_index', '?')}", kind="safety")
    safety_request_id = ""
    if safety is not None:
        safety_request_id = str(uuid.uuid4())
        bind_request(safety, safety_request_id)

    original_path = bpy.data.filepath or record.get("original_path") or ""
    window = _main_window()
    _restoring = True
    try:
        with bpy.context.temp_override(window=window):
            result = bpy.ops.wm.recover_auto_save(filepath=path)
        if 'FINISHED' not in result:
            return False, "Could not read the checkpoint"
    except Exception as e:  # noqa: BLE001
        logger.error(f"Turn checkpoint restore failed: {e}", exc_info=True)
        return False, "Could not read the checkpoint"
    finally:
        _restoring = False

    # The recovered document now points at the checkpoint file. Give a
    # titled project its own path back (the one write of the user's file:
    # the restored state, once); park an untitled one in the session's
    # working file so Ctrl-S never lands on a checkpoint.
    target = original_path or working_file(record.get("session_id", ""))
    try:
        with bpy.context.temp_override(window=_main_window()):
            bpy.ops.wm.save_as_mainfile(filepath=target)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Turn checkpoint: could not save the restored document to {os.path.basename(target)}: {e}",
                     exc_info=True)

    restored_scene = _session_scene(record.get("session_id", ""))
    _after_load(restored_scene, record, safety_request_id)
    return True, f"Restored to before turn {record.get('turn_index', '?')}"


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


def _after_load(scene, record: dict, safety_request_id: str) -> None:
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
        # new backend session. The safety copy still belongs to the old one.
        session.clear_session_id(scene)
        if safety_request_id:
            _send_backend(session_id, [("checkpoint.mark", {"session_id": session_id, "request_id": safety_request_id})])
        return
    calls = []
    if safety_request_id:
        calls.append(("checkpoint.mark", {"session_id": session_id, "request_id": safety_request_id}))
    if record.get("request_id"):
        calls.append(("checkpoint.rewind", {"session_id": session_id, "request_id": record["request_id"]}))
    else:
        _notify(scene.name, "Scene restored. This checkpoint has no conversation bookmark, so the chat memory was not rewound.")
    _send_backend(session_id, calls)


def _send_backend(session_id: str, calls: list) -> None:
    """Run the backend bookmarks/rewind on a worker thread, in order."""
    global _rewind_inflight
    if not calls:
        return
    scene_name = ""
    try:
        scene = _session_scene(session_id)
        scene_name = scene.name if scene else ""
    except Exception:  # noqa: BLE001
        pass
    with _LOCK:
        _rewind_inflight = True

    def _run():
        global _rewind_inflight
        from mixar.modules.common.agent_rpc.client import request
        failure = ""
        try:
            for method, payload in calls:
                reply = request(method, payload, mutation=True)
                logger.info(f"Turn checkpoint {method} -> {reply!r}"[:400])
                if isinstance(reply, dict) and (reply.get("ok") is False or reply.get("status") == "failure"):
                    raise RuntimeError(reply.get("message") or f"{method} refused")
                # The backend only forks when the bookmark has a checkpoint id.
                # `has_conversation: false` means NOTHING was forked, and the
                # contract says the client clears its session id so the next
                # message starts a new one. We were deciding from our own local
                # `session_was_new` instead, which is a different question --
                # so a .blend carrying a session id whose backend thread was
                # purged (or belongs to the other environment) rolled the scene
                # back while the agent kept remembering every reverted turn.
                if (method == "checkpoint.rewind" and isinstance(reply, dict)
                        and reply.get("has_conversation") is False):
                    _clear_session_on_main(scene_name)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Turn checkpoint backend call failed: {e}")
            failure = str(e)
        finally:
            with _LOCK:
                _rewind_inflight = False
        if failure:
            _notify(scene_name, "Scene restored, but the conversation could not be rewound: "
                                f"{failure}. The agent may still remember the undone turns.")

    threading.Thread(target=_run, name="mixie-turn-checkpoint", daemon=True).start()


def _clear_session_on_main(scene_name: str) -> None:
    """Drop the session id from the worker thread (bpy only on the main one)."""
    def _clear():
        try:
            import bpy
            from .session import get_session_manager
            scene = bpy.data.scenes.get(scene_name) if scene_name else None
            scene = scene or (bpy.context.window.scene if bpy.context.window else bpy.context.scene)
            if scene is not None:
                get_session_manager().clear_session_id(scene)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not clear the session id after a bookmark-less rewind: {e}")
        return None
    try:
        import bpy as _bpy
        _bpy.app.timers.register(_clear, first_interval=0.0)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Session clear timer skipped: {e}")
    _notify(scene_name, "Scene restored. That checkpoint predates the conversation, "
                        "so the next message starts a new chat.")


def _notify(scene_name: str, text: str) -> None:
    """Add an agent bubble on the main thread (safe from any thread)."""
    def _add():
        try:
            import bpy
            from .message_helpers import add_agent_message
            from .ui_utils import redraw_chat_areas
            scene = bpy.data.scenes.get(scene_name) if scene_name else None
            scene = scene or (bpy.context.window.scene if bpy.context.window else bpy.context.scene)
            add_agent_message(scene, text)
            redraw_chat_areas()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"checkpoint notice skipped: {e}")
        return None
    try:
        import bpy as _bpy
        _bpy.app.timers.register(_add, first_interval=0.05)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"checkpoint notice timer skipped: {e}")

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Local chat-history archive for Mixie Chat.

"New Chat" used to hard-clear ``scene.mixie_chat_messages`` with no way
back. This module makes it non-destructive: the current conversation is
archived to disk before the wipe, and the C++-drawn history overlay
(``mixie_chat_history_overlay.cc``, toggled by the header clock button)
lets the user reopen any archived chat.

Storage layout (sidecar — deliberately NOT inside the .mixar file, so
project files stay lean, history survives unsaved files, and shared
files never leak conversations):

    ~/.mixar/chat_history/<session_id>.json   full archived session
    ~/.mixar/chat_history/index.json          metadata index (list cache)
    ~/.mixar/chat_media/<session_id>/         copied image files

Each record stores the message transcript as the same nested dicts
produced by ``core.chat_serializer.snapshot_propgroup``, so restoring is
a straight ``restore_propgroup`` into ``scene.mixie_chat_messages``.

Reopening a chat also restores ``scene.mixie_session_id``: the backend
keeps the conversation state server-side in a LangGraph checkpoint keyed
by that id, so the next message resumes the agent's context — nothing
from the transcript is ever uploaded.

Threading: everything here runs on the main thread (operators and the
SSE-completion timer). Disk writes are a few hundred KB of JSON at turn
boundaries.
"""

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone

from mixar.config.logging_config import get_logger

from ..constants import (
    CHAT_HISTORY_MEDIA_MAX_BYTES,
    CHAT_HISTORY_TITLE_MAXLEN,
    DEV_MODE,
    MAX_ARCHIVED_SESSIONS,
)
from .chat_serializer import restore_propgroup, snapshot_propgroup

logger = get_logger(__name__)

_INDEX_FILENAME = "index.json"
_RECORD_VERSION = 1
_STOPPED_MARKER = "*Stopped*"

# Metadata keys mirrored into index.json for the popover list.
_META_KEYS = (
    "session_id",
    "title",
    "user_email",
    "file_path",
    "scene_name",
    "created_at",
    "archived_at",
    "message_count",
)

# Cached, newest-first metadata list for the popover. The panel's draw()
# runs every UI frame and must never touch disk — mutations invalidate.
_cached_sessions = None


# =============================================================================
# Paths
# =============================================================================

def _mixar_home() -> str:
    """The per-user app-data dir, shared with onboarding/operation_history."""
    return os.path.join(os.path.expanduser("~"), ".mixar")


def history_dir() -> str:
    path = os.path.join(_mixar_home(), "chat_history")
    os.makedirs(path, exist_ok=True)
    return path


def _media_root() -> str:
    return os.path.join(_mixar_home(), "chat_media")


def media_dir(session_id: str) -> str:
    return os.path.join(_media_root(), _safe_id(session_id))


def _safe_id(session_id: str) -> str:
    """Filesystem-safe form of a session id (uuid4 in practice)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:80]


def _record_path(session_id: str) -> str:
    return os.path.join(history_dir(), _safe_id(session_id) + ".json")


# =============================================================================
# JSON helpers
# =============================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _atomic_write_json(path: str, data) -> None:
    """Write via tmp+rename so a crash never leaves a half-written record."""
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        # A failed write (disk full, encoding error) must not strand the
        # uniquely-named tmp file — archive runs every turn end, so leaks
        # would accumulate one orphan per turn.
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# =============================================================================
# Index
# =============================================================================

def _meta_from_record(record: dict) -> dict:
    return {key: record.get(key) for key in _META_KEYS}


def _load_index() -> dict:
    """Return ``{session_id: meta}``; self-heal by rescanning if broken."""
    data = _read_json(os.path.join(history_dir(), _INDEX_FILENAME))
    if isinstance(data, dict) and isinstance(data.get("sessions"), dict):
        return data["sessions"]
    return _rebuild_index()


def _rebuild_index() -> dict:
    sessions = {}
    try:
        filenames = os.listdir(history_dir())
    except OSError:
        return sessions
    for filename in filenames:
        if not filename.endswith(".json") or filename == _INDEX_FILENAME:
            continue
        record = _read_json(os.path.join(history_dir(), filename))
        if isinstance(record, dict) and record.get("session_id"):
            sessions[record["session_id"]] = _meta_from_record(record)
    _write_index(sessions)
    logger.info(f"Chat history index rebuilt ({len(sessions)} session(s))")
    return sessions


def _write_index(sessions: dict) -> None:
    try:
        _atomic_write_json(
            os.path.join(history_dir(), _INDEX_FILENAME),
            {"version": _RECORD_VERSION, "sessions": sessions},
        )
    except OSError as e:
        logger.error(f"Failed to write chat history index: {e}")
    invalidate_cache()


def invalidate_cache() -> None:
    global _cached_sessions
    _cached_sessions = None


# =============================================================================
# Public API
# =============================================================================

def list_sessions(user_email: str = "") -> list:
    """Newest-first metadata for the popover. Cached; cheap per draw.

    Sessions are filtered to the given account (entries archived while
    logged out — empty ``user_email`` — are shown to everyone on this
    machine; the backend independently enforces ownership on resume).
    """
    global _cached_sessions
    if _cached_sessions is None:
        _cached_sessions = sorted(
            _load_index().values(),
            key=lambda meta: meta.get("archived_at") or "",
            reverse=True,
        )
    if not user_email:
        return list(_cached_sessions)
    return [
        meta for meta in _cached_sessions
        if (meta.get("user_email") or "") in ("", user_email)
    ]


def load_session(session_id: str):
    """Full archived record (with messages), or None."""
    record = _read_json(_record_path(session_id))
    if isinstance(record, dict) and record.get("session_id") == session_id:
        return record
    return None


def delete_session(session_id: str) -> bool:
    index = _load_index()
    existed = index.pop(session_id, None) is not None
    _delete_session_files(session_id)
    _write_index(index)
    return existed


def archive_current(scene) -> bool:
    """Archive the scene's live chat to disk (upsert by session_id).

    Returns True when a record was written. Skips quietly when there is
    nothing meaningful to keep: dev mode, no session id yet, or no USER
    message (hint/greeting-only chats). Safe to call repeatedly — the
    turn-end hook upserts after every completed turn so history survives
    a crash even if New Chat is never clicked.
    """
    if DEV_MODE or scene is None:
        return False
    session_id = getattr(scene, "mixie_session_id", "") or ""
    messages = getattr(scene, "mixie_chat_messages", None)
    if not session_id or not messages or len(messages) == 0:
        return False
    if not any(getattr(msg, "sender", "") == "USER" for msg in messages):
        return False

    snapshot = _sanitize_snapshot(
        [snapshot_propgroup(msg) for msg in messages]
    )
    if not snapshot:
        return False
    _copy_media(snapshot, session_id)

    import bpy

    now = _now_iso()
    index = _load_index()
    previous_meta = index.get(session_id) or {}
    record = {
        "version": _RECORD_VERSION,
        "session_id": session_id,
        "title": _derive_title(snapshot),
        "user_email": getattr(scene, "mixie_chat_user_id", "") or "",
        "file_path": bpy.data.filepath or "",
        "scene_name": scene.name,
        "created_at": previous_meta.get("created_at") or now,
        "archived_at": now,
        "message_count": len(snapshot),
        "messages": snapshot,
    }
    try:
        _atomic_write_json(_record_path(session_id), record)
    except (OSError, TypeError, ValueError) as e:
        logger.error(f"Failed to archive chat session {session_id[:8]}: {e}")
        return False

    index[session_id] = _meta_from_record(record)
    _prune(index)
    _write_index(index)
    logger.info(
        f"Archived chat session {session_id[:8]} "
        f"({record['message_count']} message(s))"
    )
    return True


def restore_into_scene(scene, record: dict) -> int:
    """Replace the scene's live chat with an archived record.

    Also restores ``scene.mixie_session_id`` so the next message resumes
    the backend thread. Caller is responsible for tearing down any
    running stream first (mirrors New Chat's cleanup).
    """
    coll = scene.mixie_chat_messages
    coll.clear()
    for msg_data in record.get("messages", []):
        if isinstance(msg_data, dict):
            restore_propgroup(coll.add(), msg_data)

    scene.mixie_session_id = record.get("session_id", "") or ""
    if hasattr(scene, "mixie_chat_user_has_engaged"):
        # Restored chats have content — never overlay the empty-state greeting.
        scene.mixie_chat_user_has_engaged = True
    if hasattr(scene, "mixie_chat_layout_epoch"):
        scene.mixie_chat_layout_epoch += 1  # force C++ layout rebuild

    try:
        from .markdown_parser import clear_incremental_cache
        clear_incremental_cache()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"clear_incremental_cache on restore skipped: {e}")

    return len(coll)


def format_relative_time(iso_ts: str, short: bool = False) -> str:
    """'When' label — long form for tooltips ('5m ago'), ``short`` form
    for the popover's narrow timestamp column ('5m')."""
    if not iso_ts:
        return ""
    try:
        then = datetime.fromisoformat(iso_ts)
    except ValueError:
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - then).total_seconds()
    if seconds < 60:
        return "now" if short else "just now"
    if seconds < 3600:
        minutes = int(seconds // 60)
        return f"{minutes}m" if short else f"{minutes}m ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours}h" if short else f"{hours}h ago"
    if seconds < 86400 * 30:
        days = int(seconds // 86400)
        return f"{days}d" if short else f"{days}d ago"
    return then.strftime("%b %d")


# =============================================================================
# Internals
# =============================================================================

def _sanitize_snapshot(snapshot: list) -> list:
    """Settle transient turn state in the snapshot dicts.

    Mirrors what abort does to the live scene (`_finalize_loader_bubble`,
    `_clear_interrupt_prompt`, `finalize_turn`) so an archive taken
    mid-turn reads as a cleanly stopped transcript:
      * loader-only placeholder bubbles are dropped; bubbles with content
        get the loader hidden and a '*Stopped*' marker,
      * stale interactive affordances (action buttons / input prompts)
        are stripped — their backend interrupts are gone,
      * live streaming state (ephemeral text, active thinking, RUNNING
        steps) is collapsed to its settled form.
    """
    out = []
    for msg in snapshot:
        content = msg.get("content") or ""
        if msg.get("loader_visible"):
            if not content.strip():
                continue  # loader-only placeholder — nothing to keep
            msg["loader_visible"] = False
            if _STOPPED_MARKER not in content:
                msg["content"] = content.rstrip() + "\n\n" + _STOPPED_MARKER
        if msg.get("action_items"):
            msg["action_items"] = []
        if msg.get("input_type"):
            msg["input_type"] = ""
        if msg.get("ephemeral"):
            msg["ephemeral"] = ""
        if msg.get("thinking_active"):
            msg["thinking_active"] = False
        if (msg.get("thinking_text") or "").strip():
            msg["thinking_collapsed"] = True
        for step in msg.get("step_items") or []:
            if isinstance(step, dict) and step.get("status") == "RUNNING":
                step["status"] = "DONE"
        out.append(msg)
    return out


def _derive_title(snapshot: list) -> str:
    for msg in snapshot:
        if msg.get("sender") != "USER":
            continue
        text = (msg.get("text") or msg.get("content") or "").strip()
        if not text:
            continue
        line = text.splitlines()[0].strip()
        if len(line) > CHAT_HISTORY_TITLE_MAXLEN:
            return line[: CHAT_HISTORY_TITLE_MAXLEN - 1].rstrip() + "…"
        return line
    return "Untitled chat"


def _copy_media(snapshot: list, session_id: str) -> None:
    """Copy referenced local image files into the durable media dir.

    Chat images/screenshots live in Blender's per-session temp dir today
    and vanish on restart; copying at archive time is what keeps archived
    transcripts rendering. Paths are rewritten in the snapshot dicts.
    Best-effort: any failure keeps the original path.
    """
    target_dir = media_dir(session_id)
    media_root_real = os.path.realpath(_media_root())
    copied = {}
    # CHAT_HISTORY_MEDIA_MAX_BYTES is a per-SESSION cap, and archive runs at
    # every turn end — seed the running total from what the session's media
    # dir already holds, or each archive call would admit a fresh 50 MB.
    total_bytes = 0
    try:
        if os.path.isdir(target_dir):
            with os.scandir(target_dir) as it:
                total_bytes = sum(
                    e.stat().st_size for e in it if e.is_file()
                )
    except OSError:
        pass

    def _duplicate(src: str) -> str:
        nonlocal total_bytes
        if not src or not os.path.isabs(src) or not os.path.isfile(src):
            return src
        real_src = os.path.realpath(src)
        if real_src.startswith(media_root_real + os.sep):
            return src  # already durable (restored session being re-archived)
        if src in copied:
            return copied[src]
        try:
            size = os.path.getsize(src)
            if total_bytes + size > CHAT_HISTORY_MEDIA_MAX_BYTES:
                logger.warning(
                    f"Chat media cap reached for {session_id[:8]}; "
                    f"keeping original path for {os.path.basename(src)}"
                )
                return src
            os.makedirs(target_dir, exist_ok=True)
            base = os.path.basename(src) or "file"
            dst = os.path.join(target_dir, base)
            if os.path.exists(dst):
                if os.path.getsize(dst) == size:
                    copied[src] = dst
                    return dst  # same file already copied on a prior upsert
                stem, ext = os.path.splitext(base)
                dst = os.path.join(target_dir, f"{stem}_{uuid.uuid4().hex[:8]}{ext}")
            shutil.copy2(src, dst)
            total_bytes += size
            copied[src] = dst
            return dst
        except OSError as e:
            logger.debug(f"Chat media copy skipped for {src}: {e}")
            return src

    for msg in snapshot:
        for att in msg.get("attachments") or []:
            if isinstance(att, dict) and att.get("image_source") == "FILE":
                att["image_path"] = _duplicate(att.get("image_path") or "")
        for img in msg.get("image_items") or []:
            if not isinstance(img, dict):
                continue
            for key in ("local_path", "thumbnail_url", "url"):
                value = img.get(key) or ""
                if value and os.path.exists(value):
                    img[key] = _duplicate(value)


def _prune(index: dict) -> None:
    """Drop the oldest sessions beyond MAX_ARCHIVED_SESSIONS (incl. media)."""
    overflow = len(index) - MAX_ARCHIVED_SESSIONS
    if overflow <= 0:
        return
    oldest_first = sorted(
        index.values(), key=lambda meta: meta.get("archived_at") or ""
    )
    for meta in oldest_first[:overflow]:
        session_id = meta.get("session_id") or ""
        index.pop(session_id, None)
        _delete_session_files(session_id)
        logger.info(f"Pruned archived chat session {session_id[:8]}")


def _delete_session_files(session_id: str) -> None:
    try:
        os.remove(_record_path(session_id))
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning(f"Failed to remove chat record {session_id[:8]}: {e}")
    shutil.rmtree(media_dir(session_id), ignore_errors=True)

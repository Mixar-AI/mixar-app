# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Chat history operators for Mixie Chat — Python side of the past-chats
overlay.

"New Chat" archives the current conversation to ~/.mixar/chat_history/
(see ``core/chat_history.py``). The list UI itself is a custom
C++-drawn overlay in the chat main region
(``editors/space_mixie_chat/mixie_chat_history_overlay.cc``) — Mixar
styling, hover states, its own scrolling. This module owns the data
side of the contract:

  * ``WindowManager.mixie_chat_history_visible`` — overlay visibility.
    Toggled by ``MIXIE_CHAT_OT_show_history`` (header clock button);
    the C++ side also clears it on ESC / click-away / row open.
  * ``WindowManager.mixie_chat_history_entries`` (ui/properties/history_props.py) — runtime mirror of the
    on-disk store (title in ``name``, ``session_id``, precomputed short
    ``when`` label). Rebuilt by ``sync_history_entries()`` whenever the
    overlay opens and after deletions; the C++ overlay only reads it.
  * ``mixie_chat.open_history_session`` / ``mixie_chat.delete_history_session``
    — dispatched by the C++ overlay with a ``session_id`` string prop
    (same pattern as slot-action clicks).

Reopening restores the exact transcript into ``scene.mixie_chat_messages``
and sets ``scene.mixie_session_id`` back, so the next message resumes the
backend conversation (its LangGraph checkpoint) — nothing is re-uploaded.
"""

from datetime import datetime, timezone

from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import get_session_manager
from ...core import chat_history
from ...core.main_thread_executor import cleanup as flush_executor_queue
from ...core.turn_transport import cleanup_turn_handler
from ...core.ui_utils import redraw_chat_areas
from .session_ops import send_cancel_request_async

logger = get_logger(__name__)


def _group_label(iso_ts: str) -> str:
    """Date bucket for the overlay's section headers, from the archive
    timestamp (UTC ISO) compared in the user's local calendar."""
    try:
        then = datetime.fromisoformat(iso_ts)
    except (TypeError, ValueError):
        return "Older"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc).astimezone().date()
            - then.astimezone().date()).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days <= 7:
        return "Previous 7 Days"
    if days <= 30:
        return "Previous 30 Days"
    return "Older"


def sync_history_entries(context) -> None:
    """Rebuild the WindowManager mirror from the on-disk store.

    Called when the overlay opens and after deletions — never from a
    draw callback (RNA writes are forbidden there).
    """
    wm = context.window_manager
    scene = context.scene
    user_email = getattr(scene, "mixie_chat_user_id", "") if scene else ""

    entries = wm.mixie_chat_history_entries
    entries.clear()
    try:
        sessions = chat_history.list_sessions(user_email)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chat history list failed: {e}")
        sessions = []
    for meta in sessions:
        session_id = meta.get("session_id") or ""
        if not session_id:
            continue
        entry = entries.add()
        entry.name = meta.get("title") or "Untitled chat"
        entry.session_id = session_id
        entry.archived_at = meta.get("archived_at") or ""
        entry.when = chat_history.format_relative_time(
            entry.archived_at, short=True
        )
        entry.group = _group_label(entry.archived_at)


# =============================================================================
# Operators
# =============================================================================

class MIXIE_CHAT_OT_show_history(Operator):
    """Toggle the past-chats overlay (syncs the list when opening)."""

    bl_idname = "mixie_chat.show_history"
    bl_label = "Chat History"
    bl_description = "Browse past chats"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        wm = context.window_manager
        # Already showing chats: close. Showing checkpoints (same card,
        # other mode): switch to chats, do not close.
        opening = not (wm.mixie_chat_history_visible and wm.mixie_chat_history_mode == 'CHATS')
        if opening:
            sync_history_entries(context)
            # The past-chats, project-rules and scribble overlays are all
            # modal over the same chat surface — only one may be open at a
            # time.
            if getattr(wm, 'mixie_chat_rules_visible', False):
                wm.mixie_chat_rules_visible = False
            if getattr(wm, 'mixie_chat_ink_visible', False):
                # Convert un-committed strokes before closing the canvas —
                # the C++ closing edge cannot dispatch the commit itself.
                from ...core.scribble import flush_pending_ink
                flush_pending_ink()
                wm.mixie_chat_ink_visible = False
        if opening:
            wm.mixie_chat_history_mode = 'CHATS'
            wm.mixie_chat_history_notice = ""
            wm.mixie_chat_history_locked = False
        wm.mixie_chat_history_visible = opening
        redraw_chat_areas()
        return {'FINISHED'}


class MIXIE_CHAT_OT_open_history_session(Operator):
    """Reopen an archived chat session (dispatched by the C++ overlay)."""

    bl_idname = "mixie_chat.open_history_session"
    bl_label = "Open Chat"
    bl_description = (
        "Reopen this chat — the current chat is saved to History first"
    )
    bl_options = {'REGISTER', 'INTERNAL'}

    session_id: StringProperty(
        name="Session ID",
        description="Archived session to reopen",
        default="",
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        scene = context.scene
        scene_name = scene.name
        session = get_session_manager()

        if not self.session_id:
            return {'CANCELLED'}
        if getattr(scene, "mixie_session_id", "") == self.session_id:
            self.report({'INFO'}, "This chat is already open")
            return {'CANCELLED'}

        record = chat_history.load_session(self.session_id)
        if not record:
            # Stale row (pruned or deleted behind our back) — refresh list.
            chat_history.invalidate_cache()
            sync_history_entries(context)
            self.report({'ERROR'}, "Chat not found in history")
            return {'CANCELLED'}

        # Tear down any in-flight turn, exactly like New Chat does.
        old_session_id = session.get_session_id(scene)
        cleanup_turn_handler(scene_name)
        from ...core.queue_processor import cleanup_event_queue_for_scene
        cleanup_event_queue_for_scene(scene_name)
        flush_executor_queue()
        if old_session_id:
            send_cancel_request_async(old_session_id)

        # Save the outgoing chat before replacing it — switching must
        # never lose anything. Best-effort, same as New Chat.
        try:
            chat_history.archive_current(scene)
        except Exception as e:
            logger.error(f"Failed to archive chat before switch: {e}")
            self.report({'WARNING'}, "Could not save the current chat to History")

        count = chat_history.restore_into_scene(scene, record)

        # Reset session state (keep connected if connected) — mirrors
        # MIXIE_CHAT_OT_new_session. The old run is cancelled above; the
        # restored chat starts with none.
        session.set_run(scene, "", False)
        if session.is_connected(scene):
            session.clear_streaming()
            session.set_connected(scene)

        # A prior switch fenced this session and marked its local turns done.
        # Reopen it explicitly so status discovery can offer server recovery.
        from ...core.turn_events import reopen
        from ...core.turn_resume import check_orphaned_turns
        reopen(scene)
        check_orphaned_turns()

        # Close the overlay (the C++ side also does this on row click;
        # kept here so any other invocation path behaves the same).
        wm = context.window_manager
        if hasattr(wm, "mixie_chat_history_visible"):
            wm.mixie_chat_history_visible = False

        redraw_chat_areas()
        title = record.get("title") or "chat"
        logger.info(
            f"Reopened archived chat {self.session_id[:8]} ({count} message(s))"
        )
        self.report({'INFO'}, f"Reopened: {title}")
        return {'FINISHED'}


class MIXIE_CHAT_OT_delete_history_session(Operator):
    """Delete an archived chat session from history."""

    bl_idname = "mixie_chat.delete_history_session"
    bl_label = "Delete Chat From History?"
    bl_description = "Remove this chat from History (cannot be undone)"
    bl_options = {'REGISTER', 'INTERNAL'}

    session_id: StringProperty(
        name="Session ID",
        description="Archived session to delete",
        default="",
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if not self.session_id:
            return {'CANCELLED'}
        if chat_history.delete_session(self.session_id):
            self.report({'INFO'}, "Chat removed from history")
        # Keep the open overlay's rows in step with the store.
        sync_history_entries(context)
        redraw_chat_areas()
        return {'FINISHED'}


# =============================================================================
# Registration — the WindowManager mirror properties live in
# ui/properties/history_props.py (registered first by the UI loader).
# =============================================================================

classes = (
    MIXIE_CHAT_OT_show_history,
    MIXIE_CHAT_OT_open_history_session,
    MIXIE_CHAT_OT_delete_history_session,
)

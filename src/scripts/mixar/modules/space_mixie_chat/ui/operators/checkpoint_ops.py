# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn checkpoints — the native Checkpoints card and the revert operator.

Data side: ``core/turn_checkpoints.py`` (capture before every fresh turn,
one timeline per chat). The card shows the applied turns, the reverted
turns and the hand-edit safety copies; clicking a row twice reverts,
reapplies or brings back (in memory, nothing written) and asks the backend
to rewind the conversation to the same point.
"""

from bpy.props import StringProperty
from bpy.types import Operator

from ...core import turn_checkpoints
from ...core.chat_history import format_relative_time
from ...core.ui_utils import redraw_chat_areas

GROUP_TURNS = "Turns"
GROUP_REVERTED = "Reverted turns"
GROUP_SAFETY = "Safety copies"


def checkpoint_row_title(item: dict) -> str:
    """One card row: "Turn 3 · add a chandelier" (the time is its own
    column), or "Safety copy · your edits after turn 2"."""
    kind = item.get("kind", "turn")
    head = f"Turn {item.get('turn_index', '?')}" if kind == "turn" else "Safety copy"
    label = (item.get("label") or "").strip()
    if label:
        return f"{head} · {label if len(label) <= 48 else label[:47] + '…'}"
    return head


def checkpoint_row_action(line: dict, item: dict) -> str:
    """The armed-row prompt: what the second click does, turns named."""
    verb, first, last = turn_checkpoints.describe_jump(line, item)
    if verb == "bring back":
        return "Bring back?"
    head = "Revert" if verb == "revert" else "Reapply"
    return f"{head} this turn?" if first == last else f"{head} turns {first}–{last}?"


def sync_checkpoint_entries(context) -> None:
    """Fill the native card with this chat's timeline and switch it to
    CHECKPOINTS mode: applied turns (newest first), then the reverted turns,
    then the safety copies, each under its own section header; the lock
    state and its reason ride along so the card can explain itself instead
    of failing a click."""
    wm = context.window_manager
    scene = context.scene
    session_id = turn_checkpoints.checkpoint_session_id(scene)
    line = turn_checkpoints.timeline(session_id, scene)
    entries = wm.mixie_chat_history_entries
    entries.clear()
    for group, items in ((GROUP_TURNS, line["applied"]),
                         (GROUP_REVERTED, line["reverted"]),
                         (GROUP_SAFETY, line["safety"])):
        for item in items:
            entry = entries.add()
            entry.name = checkpoint_row_title(item)
            entry.session_id = item["id"]
            entry.archived_at = item.get("created_at", "") or ""
            entry.when = format_relative_time(entry.archived_at, short=True)
            entry.group = group
            entry.action = checkpoint_row_action(line, item)
    allowed, reason = turn_checkpoints.can_restore(scene)
    wm.mixie_chat_history_locked = not allowed
    wm.mixie_chat_history_notice = "" if allowed else reason
    wm.mixie_chat_history_mode = 'CHECKPOINTS'


class MIXIE_CHAT_OT_show_checkpoints(Operator):
    """Open the native Checkpoints card (the same card as past chats, in
    CHECKPOINTS mode): rows arm on the first click and act on the second,
    which is the confirmation; there is no modal dialog."""

    bl_idname = "mixie_chat.show_checkpoints"
    bl_label = "Checkpoints"
    bl_description = "Revert or reapply turns of this chat"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        wm = context.window_manager
        already = (wm.mixie_chat_history_visible
                   and wm.mixie_chat_history_mode == 'CHECKPOINTS')
        if already:
            wm.mixie_chat_history_visible = False
            redraw_chat_areas()
            return {'FINISHED'}
        sync_checkpoint_entries(context)
        # One modal overlay at a time over the chat surface.
        if getattr(wm, 'mixie_chat_rules_visible', False):
            wm.mixie_chat_rules_visible = False
        if getattr(wm, 'mixie_chat_ink_visible', False):
            from ...core.scribble import flush_pending_ink
            flush_pending_ink()
            wm.mixie_chat_ink_visible = False
        wm.mixie_chat_history_visible = True
        redraw_chat_areas()
        return {'FINISHED'}


class MIXIE_CHAT_OT_restore_checkpoint(Operator):
    """Revert to, reapply through, or bring back one checkpoint row.

    The state being left is captured first when nothing else holds it (the
    tip, or hand edits), so the jump itself can be undone from the card."""

    bl_idname = "mixie_chat.restore_checkpoint"
    bl_label = "Revert Turn"
    bl_description = (
        "Revert or reapply turns of this chat — the scene and the "
        "conversation move together, nothing is written to your file"
    )
    bl_options = {'INTERNAL'}

    checkpoint_id: StringProperty(
        name="Checkpoint ID",
        default="",
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        if not self.checkpoint_id:
            return {'CANCELLED'}
        screen = getattr(context.window, "screen", None) if context.window else None
        if screen is not None and getattr(screen, "is_temporary", False):
            # Invoked from the chat island (a temporary companion window
            # that the file read closes): run it on the next tick instead
            # of on this operator's call stack.
            turn_checkpoints.restore_deferred(context.scene.name, self.checkpoint_id)
            self.report({'INFO'}, "Restoring checkpoint…")
            return {'FINISHED'}
        ok, message = turn_checkpoints.restore(context.scene, self.checkpoint_id)
        self.report({'INFO'} if ok else {'ERROR'}, message)
        return {'FINISHED'} if ok else {'CANCELLED'}


classes = (
    MIXIE_CHAT_OT_show_checkpoints,
    MIXIE_CHAT_OT_restore_checkpoint,
)

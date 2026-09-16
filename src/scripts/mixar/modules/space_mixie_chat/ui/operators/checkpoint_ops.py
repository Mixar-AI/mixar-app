# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn checkpoints — the header menu and the restore operator.

Data side: ``core/turn_checkpoints.py`` (capture before every fresh turn,
restore while idle). The menu lists the session's checkpoints newest first;
picking one swaps the document back and asks the backend to rewind the
conversation to the same turn.
"""

from bpy.props import StringProperty
from bpy.types import Menu, Operator

from mixar.config.logging_config import get_logger

from ...core import get_session_manager
from ...core import turn_checkpoints
from ...core.chat_history import format_relative_time

logger = get_logger(__name__)


def checkpoint_row_label(item: dict) -> str:
    """One menu row: "Turn 3 · add a chandelier · 5m ago"."""
    kind = item.get("kind", "turn")
    head = f"Turn {item.get('turn_index', '?')}" if kind == "turn" else "Safety copy"
    label = (item.get("label") or "").strip()
    when = format_relative_time(item.get("created_at", ""), short=True)
    parts = [head]
    if label:
        parts.append(label if len(label) <= 48 else label[:47] + "…")
    if when:
        parts.append(when)
    return " · ".join(parts)


class MIXIE_CHAT_MT_checkpoints(Menu):
    """Checkpoints taken before each turn of this chat."""

    bl_idname = "MIXIE_CHAT_MT_checkpoints"
    bl_label = "Checkpoints"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        session_id = get_session_manager().get_session_id(scene)
        items = turn_checkpoints.list_checkpoints(session_id)
        if not items:
            layout.label(text="No checkpoints yet", icon='INFO')
            return
        allowed, reason = turn_checkpoints.can_restore(scene)
        if not allowed:
            layout.label(text=reason, icon='INFO')
            layout.separator()
        column = layout.column()
        column.enabled = allowed
        for item in items:
            op = column.operator(
                "mixie_chat.restore_checkpoint",
                text=checkpoint_row_label(item),
                icon='RECOVER_LAST' if item.get("kind") == "turn" else 'FILE_BACKUP',
            )
            op.checkpoint_id = item["id"]


class MIXIE_CHAT_OT_restore_checkpoint(Operator):
    """Put the scene and the chat back to this checkpoint.

    The current state is kept as a safety checkpoint first, so the restore
    itself can be undone from the same menu."""

    bl_idname = "mixie_chat.restore_checkpoint"
    bl_label = "Restore Checkpoint"
    bl_description = (
        "Put the scene and chat back to this point — the current state is "
        "kept as a safety checkpoint"
    )
    bl_options = {'REGISTER', 'INTERNAL'}

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
        ok, message = turn_checkpoints.restore(context.scene, self.checkpoint_id)
        self.report({'INFO'} if ok else {'ERROR'}, message)
        return {'FINISHED'} if ok else {'CANCELLED'}


classes = (
    MIXIE_CHAT_MT_checkpoints,
    MIXIE_CHAT_OT_restore_checkpoint,
)

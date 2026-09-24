# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager properties behind the native past-chats / Checkpoints card.

The C++ overlay (``mixie_chat_history_overlay.cc``) reads these; Python
fills them (``history_ops.sync_history_entries``,
``checkpoint_ops.sync_checkpoint_entries``). Session state, never persisted.
``mixie_chat_undo_stamp`` is written by the native ``mixie_chat.undo_stamp``
operator and read back by ``core/checkpoint_timeline.undo_stamp``.
"""

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, StringProperty
from bpy.types import PropertyGroup


class MixieChatHistoryEntry(PropertyGroup):
    """One archived session row for the C++ history overlay.

    ``name`` (inherited) holds the chat title.
    """
    session_id: StringProperty(
        name="Session ID",
        description="Archived session identifier",
        default="",
    )
    archived_at: StringProperty(
        name="Archived At",
        description="ISO timestamp of the last archive",
        default="",
    )
    when: StringProperty(
        name="When",
        description="Short relative-time label ('now', '5m', '3h', "
                    "'2d', 'Jul 11') precomputed at sync time — the C++ "
                    "overlay renders it verbatim",
        default="",
    )
    group: StringProperty(
        name="Group",
        description="Section label precomputed at sync time — a date bucket "
                    "('Today', 'Yesterday', ...) for chats, 'Turns' / "
                    "'Reverted turns' / 'Safety copies' for checkpoints; the "
                    "C++ overlay draws a header whenever it changes between "
                    "consecutive rows",
        default="",
    )
    action: StringProperty(
        name="Action",
        description="Checkpoints: what a second click on the armed row does "
                    "('Revert turns 3–5?'); the C++ overlay draws it in place "
                    "of the time while the row is armed",
        default="",
    )


classes = (MixieChatHistoryEntry,)

_WM_ATTRS = ("mixie_chat_history_entries", "mixie_chat_history_visible",
             "mixie_chat_history_mode", "mixie_chat_history_notice",
             "mixie_chat_undo_stamp", "mixie_chat_history_locked")


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass  # already registered (module reload)

    # Runtime mirror of ~/.mixar/chat_history read by the C++ overlay.
    # Session state, never persisted.
    bpy.types.WindowManager.mixie_chat_history_entries = CollectionProperty(
        type=MixieChatHistoryEntry,
        name="Chat History Entries",
        options={'SKIP_SAVE'},
    )
    # Overlay visibility — written here (header toggle) and by the C++
    # overlay (ESC / click-away / row open all clear it).
    bpy.types.WindowManager.mixie_chat_history_visible = BoolProperty(
        name="Chat History Visible",
        description="Whether the past-chats overlay is open",
        default=False,
        options={'SKIP_SAVE'},
    )
    # The same native card lists past chats or the turn checkpoints
    # (checkpoint_ops.sync_checkpoint_entries fills the entries and sets
    # the mode). Checkpoints add a lock (agent busy) with its reason.
    bpy.types.WindowManager.mixie_chat_history_mode = EnumProperty(
        name="Chat Card Mode",
        items=[('CHATS', "Chats", "Past chats"),
               ('CHECKPOINTS', "Checkpoints", "Turn checkpoints of this chat")],
        default='CHATS',
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixie_chat_history_notice = StringProperty(
        name="Chat Card Notice", default="", options={'SKIP_SAVE'},
        description="Footer line shown by the checkpoints card (why it is locked)",
    )
    # Written by the native mixie_chat.undo_stamp operator, read right back
    # by turn_checkpoints.undo_stamp(): "has the document changed since the
    # last checkpoint jump" is answered by Blender's undo stack.
    bpy.types.WindowManager.mixie_chat_undo_stamp = StringProperty(
        name="Undo Stamp", default="", options={'SKIP_SAVE'},
        description="Fingerprint of the undo stack (step count and active step)",
    )
    bpy.types.WindowManager.mixie_chat_history_locked = BoolProperty(
        name="Chat Card Locked", default=False, options={'SKIP_SAVE'},
        description="Checkpoint rows cannot be restored right now",
    )


def unregister():
    for attr in _WM_ATTRS:
        try:
            delattr(bpy.types.WindowManager, attr)
        except Exception:
            pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

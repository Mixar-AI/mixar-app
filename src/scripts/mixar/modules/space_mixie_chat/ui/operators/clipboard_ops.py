# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Clipboard operators for Mixie Chat.

Handles paste operations for text and images.

Note: The per-bubble copy button is handled entirely in C++
(mixie_chat_hit_testing.cc → WM_clipboard_text_set). These Python
operators are only for keyboard/menu-driven copy and paste.

Three paste entry points, deliberately kept distinct:

* ``mixie_chat.paste_image`` — image only. It returns ``CANCELLED`` when the
  clipboard holds no image, and ``interface_handlers.cc`` depends on that:
  while the composer is in text-edit mode the C++ hook calls this operator
  first and, on ``CANCELLED``, runs its own ``ui_textedit_copypaste`` so text
  lands at the cursor. Do not give this operator a text fallback.
* ``mixie_chat.paste`` — the keymap-bound chord. Image first, then text.
  This is the path taken whenever the composer does *not* hold text-edit
  focus, which is the normal state after the window has been deactivated —
  and it is exactly the state an external dictation / paste utility leaves
  behind when it injects Ctrl/Cmd+V. Before this operator existed the plain
  chord was bound to ``paste_image`` alone, so every such paste was silently
  dropped.
* ``mixie_chat.paste_text`` — text only, for menus and scripts.
"""

import os

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...constants import (
    CHAT_INPUT_MAXLEN,
    MAX_ATTACHMENTS_PER_MESSAGE,
)
from ...core import validate_image_file
from ...core.attachment_board_sync import mirror_attachment_to_moodboard
from ...core.clipboard_image import read_clipboard_image
from ...core.ui_utils import redraw_chat_areas, sync_bubble_attachment_size_deferred

logger = get_logger(__name__)

# The control character interface_handlers.cc appends to the composer buffer to
# mean "Enter was pressed"; chat_props.py's update callback strips it and
# submits. Pasted text must never carry one — see normalize_pasted_text().
SUBMIT_MARKER = "\x1F"


def normalize_pasted_text(text):
    r"""Make clipboard text safe to append to the composer.

    Two things have to go. CRLF, because the composer stores plain "\n"
    newlines (Shift+Enter inserts one) and a stray "\r" renders as a box.
    And SUBMIT_MARKER, because ``scene.mixie_chat_input``'s update callback
    treats that control character as "the user pressed Enter" — a clipboard
    that happened to carry one would send the message mid-paste.
    """
    if not text:
        return ""
    return (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace(SUBMIT_MARKER, "")
    )


def append_clipboard_text_to_input(context, report=None):
    """Append the clipboard's text to the chat composer.

    Returns True when something was inserted. Appends rather than inserting
    at the caret on purpose: this path only runs while the composer is NOT
    in text-edit mode, so there is no caret to insert at — when there is one,
    the C++ hook in ``interface_handlers.cc`` handles the paste itself and
    consumes the event before any keymap sees it.
    """
    scene = getattr(context, "scene", None)
    if scene is None:
        return False

    # Get clipboard text via operator context (not bpy.context)
    clipboard_text = normalize_pasted_text(context.window_manager.clipboard)

    if not clipboard_text:
        return False

    # Append clipboard to current input (at end)
    new_input = scene.mixie_chat_input + clipboard_text

    # Clamp to the composer property's own maxlen (CHAT_INPUT_MAXLEN, the
    # RNA limit on scene.mixie_chat_input) so a long paste warns instead of
    # being silently truncated by RNA at a different, smaller bound.
    if len(new_input) > CHAT_INPUT_MAXLEN:
        if report is not None:
            report({'WARNING'},
                   f"Pasted text too long (max {CHAT_INPUT_MAXLEN} chars)")
        new_input = new_input[:CHAT_INPUT_MAXLEN]

    scene.mixie_chat_input = new_input
    redraw_chat_areas()

    logger.debug(f"Pasted {len(clipboard_text)} characters into chat input")
    return True


# Island tabs whose pasted image is the pane's reference (mirrors
# agent_bubble.core.pane_references.PANE_TABS; kept literal so this module
# does not import agent_bubble at load time).
_PANE_TABS = frozenset({'THREE_D', 'IMAGE', 'VIDEO', 'SPLAT'})


def active_pane_tab(context):
    """The island generation tab a paste in this context belongs to, or None.

    Only a paste made inside the Agent Bubble follows its tab; the Agent,
    Library and Queue tabs (and every other chat surface) keep attaching to
    the Agent composer.
    """
    area = getattr(context, "area", None)
    if area is None or getattr(area, "type", None) != 'AGENT_BUBBLE':
        return None
    tab = getattr(context.window_manager, "mixar_bubble_tab", 'AGENT')
    return tab if tab in _PANE_TABS else None


class MIXIE_CHAT_OT_paste_text(Operator):
    """Paste text from clipboard into chat input field"""
    bl_idname = "mixie_chat.paste_text"
    bl_label = "Paste Text"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        """Allow paste when chat area is active."""
        return context.scene is not None

    def execute(self, context):
        if append_clipboard_text_to_input(context, self.report):
            return {'FINISHED'}
        return {'CANCELLED'}


class MIXIE_CHAT_OT_paste(Operator):
    """Paste clipboard contents into the chat composer"""
    bl_idname = "mixie_chat.paste"
    bl_label = "Paste"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        """Allow paste when a chat surface is active."""
        return context.scene is not None

    def execute(self, context):
        # An image on the clipboard becomes an attachment, same as the
        # explicit Ctrl/Cmd+Shift+V chord.
        try:
            image_result = bpy.ops.mixie_chat.paste_image()
        except RuntimeError as exc:  # poll failed / operator unavailable
            logger.debug(f"paste_image unavailable, pasting text instead: {exc}")
            image_result = {'CANCELLED'}

        if 'FINISHED' in image_result:
            return {'FINISHED'}

        # Otherwise it is a text paste. This is the branch an external
        # dictation tool lands in: it drops its transcript on the clipboard
        # and injects Ctrl/Cmd+V, by which point the composer has lost
        # text-edit focus and the C++ inline paste path is out of reach.
        if append_clipboard_text_to_input(context, self.report):
            return {'FINISHED'}

        return {'CANCELLED'}


class MIXIE_CHAT_OT_paste_image(Operator):
    """Paste image from clipboard as attachment"""
    bl_idname = "mixie_chat.paste_image"
    bl_label = "Paste Image"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        """Allow when chat area is active.
        Attachment limit is checked in execute, not poll."""
        return context.scene is not None

    def execute(self, context):
        try:
            img_path = read_clipboard_image()

            if not img_path:
                # No image on clipboard — return CANCELLED so the C++
                # caller (interface_handlers.cc) falls back to its own
                # ui_textedit_copypaste for normal text paste.
                return {'CANCELLED'}

            # Validate pasted image
            is_valid, error = validate_image_file(img_path)

            if not is_valid:
                self.report({'ERROR'}, f"Invalid image: {error}")
                self._safe_remove(img_path)
                return {'CANCELLED'}

            # On the island's 3D / Image / Video / Splat tabs the image is
            # that pane's reference, exactly like its own upload — not a
            # hidden Agent-composer attachment.
            pane = active_pane_tab(context)
            if pane is not None:
                return self._attach_to_pane(context, pane, img_path)

            # Check attachment limit
            scene = context.scene
            attachments = scene.mixie_chat_pending_attachments
            if len(attachments) >= MAX_ATTACHMENTS_PER_MESSAGE:
                self.report({'WARNING'},
                           f"Max {MAX_ATTACHMENTS_PER_MESSAGE} attachments")
                self._safe_remove(img_path)
                return {'CANCELLED'}

            # Add to pending attachments
            attachment = attachments.add()
            attachment.image_path = img_path
            attachment.image_source = 'FILE'
            attachment.display_name = os.path.basename(img_path)

            # The pasted file lives in the temp directory; the moodboard's
            # import path packs it, so the board item survives cleanup.
            mirror_attachment_to_moodboard(scene, img_path, 'FILE')

            redraw_chat_areas()
            sync_bubble_attachment_size_deferred(force_attachment_height=True)

            # Tag footer region for thumbnail update
            for area in context.screen.areas:
                if area.type == 'AGENT_BUBBLE':
                    for region in area.regions:
                        if region.type == 'TOOLS':
                            region.tag_redraw()

            self.report({'INFO'}, "Pasted image from clipboard")
            return {'FINISHED'}

        except Exception as e:
            logger.error(f"Failed to paste image: {e}")
            self.report({'ERROR'}, f"Paste failed: {str(e)}")
            return {'CANCELLED'}

    def _attach_to_pane(self, context, pane, img_path):
        from mixar.modules.agent_bubble.core.pane_references import (
            attach_file_to_pane,
            redraw_bubbles,
        )

        try:
            attach_file_to_pane(context.scene, pane, img_path, "Pasted Image")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Could not attach pasted image to {pane} tab: {exc}")
            self.report({'ERROR'}, f"Could not attach pasted image: {exc}")
            self._safe_remove(img_path)
            return {'CANCELLED'}
        redraw_bubbles(context.window_manager)
        self.report({'INFO'}, "Pasted image as reference")
        return {'FINISHED'}

    @staticmethod
    def _safe_remove(path):
        """Remove a file, ignoring errors if it doesn't exist."""
        try:
            os.remove(path)
        except OSError:
            pass


classes = (
    MIXIE_CHAT_OT_paste_text,
    MIXIE_CHAT_OT_paste_image,
    MIXIE_CHAT_OT_paste,
)

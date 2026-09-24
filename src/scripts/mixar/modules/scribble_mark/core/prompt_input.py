# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Type into the Agent draft without leaving the frozen drawing surface."""

from mixar.modules.space_mixie_chat.constants import CHAT_INPUT_MAXLEN


def handle(context, event, report):
    """Handle text presses at the draft's end; drawing shortcuts stay modal-owned.

    There is no text caret in the viewport. Release a previous composer edit
    before changing RNA so its private buffer cannot overwrite these words.
    Enter uses the composer's send path; Shift+Enter inserts a newline.
    """
    if event.value != "PRESS":
        return False

    command = event.ctrl or event.oskey
    erase = event.type == "BACK_SPACE" and not command and not event.alt
    if event.type == "V" and command and not event.alt and not event.shift:
        text = context.window_manager.clipboard
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x1f", "")
    elif event.type in {"RET", "NUMPAD_ENTER"} and not command and not event.alt:
        if not event.shift:
            # Reuse native composer preflight/reporting and pending-ink flush.
            # A submit marker would truncate a draft already at its RNA limit.
            if not getattr(event, "is_repeat", False):
                from mixar.modules.space_mixie_chat.core import scribble
                from mixar.modules.space_mixie_chat.ui.properties.chat_props import (
                    _execute_send_message,
                )

                scribble.release_composer()
                _execute_send_message()
            return True
        text = "\n"
    elif command and not event.alt:
        return False
    else:
        # Keep OS-produced Unicode, including Option/AltGr characters and
        # combining marks. Control characters must never become Send markers.
        text = "".join(c for c in event.unicode if ord(c) >= 32 and ord(c) != 127)

    if not text and not erase:
        return False

    from mixar.modules.space_mixie_chat.core import scribble
    from mixar.modules.space_mixie_chat.core.ui_utils import redraw_chat_areas

    scribble.release_composer()
    current = context.scene.mixie_chat_input
    value = current[:-1] if erase else current + text
    if len(value) > CHAT_INPUT_MAXLEN:
        report({"WARNING"}, f"Agent draft is full (max {CHAT_INPUT_MAXLEN} characters)")
        value = value[:CHAT_INPUT_MAXLEN]
    context.scene.mixie_chat_input = value
    redraw_chat_areas()
    return True

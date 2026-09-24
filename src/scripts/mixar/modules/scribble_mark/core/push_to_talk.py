# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hold left Option (macOS) / left Alt (Windows) over the frozen viewport to talk.

The same gesture as the chat composer's native hold
(``interface_text_dictation.cc``): the key held ALONE for ``HOLD_SECONDS``
starts dictation into the Agent draft, a tap does nothing, another key during
the wait turns it into an ordinary modifier chord (Option characters still
type), release keeps the words and Esc drops them. One deliberate difference:
a mouse press during a hold is drawing, not a chord, so the user can circle
something while describing it.

The chat's release fallback keymap (``mixie_chat.voice_push_to_talk_release``)
also ends an owned hold, so a release this modal never sees still finishes.
"""

import time

from mixar.modules.space_mixie_chat.constants import VOICE_INPUT_SUPPORTED

# Lockstep with HOLD_SECONDS in interface_text_dictation.cc.
HOLD_SECONDS = 0.30
TRIGGER = "LEFT_ALT"
_POINTER = frozenset({
    "LEFTMOUSE", "RIGHTMOUSE", "MIDDLEMOUSE", "MOUSEMOVE", "INBETWEEN_MOUSEMOVE",
    "PEN", "ERASER", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN", "TRACKPADZOOM",
})


def _voice():
    from mixar.modules.space_mixie_chat.core import voice
    return voice


class HoldToTalk:
    """Per-freeze hold state. ``handle`` returns True when it consumed the event."""

    def __init__(self, clock=time.monotonic, on_status=None):
        self._clock = clock
        # The frozen viewport only repaints when tagged, and the voice status
        # the hint shows changes on the coordinator's timer, not on an event.
        self._on_status = on_status
        self._status = ""
        self.pressed_at = None
        self.started = False

    def _watch_status(self, context):
        wm = getattr(context, "window_manager", None)
        status = getattr(wm, "mixie_chat_voice_status", "")
        if isinstance(status, str) and status != self._status:
            self._status = status
            if self._on_status is not None:
                self._on_status()

    def _reset(self):
        self.pressed_at = None
        self.started = False

    def _begin(self, context):
        if _voice().push_to_talk_begin(context) == "started":
            self.started = True
        else:
            self._reset()

    def _end(self, discard=False):
        _voice().push_to_talk_end(discard=discard)
        self._reset()

    def handle(self, context, event, inside):
        if not VOICE_INPUT_SUPPORTED:
            return False
        kind, value = event.type, event.value

        if kind == "WINDOW_DEACTIVATE":
            # The release will never arrive; the chat discards here too.
            if self.started:
                self._end(discard=True)
            self._reset()
            return False

        if kind == TRIGGER and value == "RELEASE":
            if self.started:
                self._end()
                return True
            if self.pressed_at is not None:
                self._reset()  # a tap stays a tap
                return True
            return False

        if kind == "TIMER":
            self._watch_status(context)
            if (self.pressed_at is not None and not self.started
                    and self._clock() - self.pressed_at >= HOLD_SECONDS):
                self._begin(context)
            return False

        if value != "PRESS":
            return False

        if kind == TRIGGER:
            if self.pressed_at is not None:
                return True  # key repeat while held
            bare = not (event.ctrl or event.oskey or event.shift)
            if (inside and bare and not getattr(event, "is_repeat", False)
                    and not _voice().is_listening()):
                self.pressed_at = self._clock()
                return True
            return False

        if self.pressed_at is None or kind in _POINTER:
            return False
        if self.started and kind == "ESC":
            self._end(discard=True)
            return True
        # Any other key makes this a modifier chord: drop the hold, keep the key.
        if self.started:
            self._end(discard=True)
        self._reset()
        return False

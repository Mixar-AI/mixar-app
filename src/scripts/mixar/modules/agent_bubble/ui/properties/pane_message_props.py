# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The agent island's PANE MESSAGE channel.

The island is a floating always-on-top window with no status bar and no Info
editor, so a generation operator's ``self.report(...)`` reaches the user
nowhere: they press Generate and nothing happens on screen. The panes
therefore paint one message line of their own, above the prompt box.

This module is where that line's text comes from. It is deliberately a
DEDICATED channel and not Blender's global report list: that list collects
reports from everything in the app — including Mixar's own agent running
sandboxed Blender scripts — so a pane sourced from it painted unrelated bpy
script output above the user's prompt. Only the pane's own action writes
here (``moodboard/ui/operators/prompt_generate_ops.py``, the one dispatcher
every pane's Generate and Enter route through), so whatever the line shows is
always about the click the user just made.

Three properties, written together by :func:`set_pane_message`:

* ``mixar_pane_message`` — the text.
* ``mixar_pane_message_level`` — one of the ``LEVEL_*`` constants below.
  Deliberately NOT Blender's ``eReportType`` bits: this channel has nothing to
  do with the report system and must not inherit its flag arithmetic.
* ``mixar_pane_message_serial`` — bumped on EVERY write, a repeat of the same
  text included, so the C++ painter can tell "said again" (restart the
  freshness timer) from "still showing" (let it expire).

WindowManager, never Scene: this is per-session UI state and must never be
serialized into a shared ``.blend`` or participate in undo — hence
``SKIP_SAVE`` on all three.

The names and the level values are a CONTRACT with
``space_agent_bubble/agent_ui_pane_kit_feedback.cc``, which reads them by
name and degrades to painting nothing when they are absent. Pinned by
``tests/test_pane_feedback.py``.
"""

import bpy
from bpy.props import IntProperty, StringProperty

#: Nothing to say. The painter draws no line.
LEVEL_NONE = 0
#: A confirmation — the action went through. Drawn dim.
LEVEL_INFO = 1
#: The action did not run, but nothing is broken. Drawn amber.
LEVEL_WARNING = 2
#: The action was refused or failed outright. Drawn red.
LEVEL_ERROR = 3

#: Every WindowManager property this module owns, in the order it registers
#: them. The C++ painter reads exactly these names, so the tuple is the thing
#: a test can compare both sides against.
PROP_NAMES = (
    "mixar_pane_message",
    "mixar_pane_message_level",
    "mixar_pane_message_serial",
)

_TEXT_PROP, _LEVEL_PROP, _SERIAL_PROP = PROP_NAMES


def _redraw_bubbles(_self, context):
    """Repaint every island so the message appears immediately.

    Hung off the SERIAL property alone — it is written last, so one redraw
    lands after the whole message is in place rather than three redraws
    painting a half-written one.
    """
    wm = context.window_manager if context else bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'AGENT_BUBBLE':
                area.tag_redraw()


def set_pane_message(text, level=LEVEL_INFO):
    """Say `text` at `level` on the island's generation panes.

    The ONE writer of the channel: text, level and serial always move
    together, so a caller can never leave the level describing a previous
    message. The serial is bumped unconditionally — repeating a message is
    news too (the user pressed Generate again and it was refused again).

    Best-effort: a failure here must never break the generation it is
    reporting on, and the island may not be registered at all.
    """
    try:
        wm = bpy.context.window_manager
        if wm is None:
            return
        setattr(wm, _TEXT_PROP, str(text or ""))
        setattr(wm, _LEVEL_PROP, int(level))
        setattr(wm, _SERIAL_PROP, int(getattr(wm, _SERIAL_PROP, 0)) + 1)
    except Exception:  # noqa: BLE001 — a message is never worth an exception
        pass


def clear_pane_message():
    """Wipe the line. Still a write, so it still bumps the serial."""
    set_pane_message("", LEVEL_NONE)


def register():
    wm = bpy.types.WindowManager
    wm.mixar_pane_message = StringProperty(
        name="Pane Message",
        description=(
            "Message the agent island's generation panes paint above the "
            "prompt box, written only by the panes' own Generate dispatcher"
        ),
        default="",
        options={'SKIP_SAVE'},
    )
    wm.mixar_pane_message_level = IntProperty(
        name="Pane Message Level",
        description=(
            "Severity of the pane message: 0 none, 1 info, 2 warning, 3 error"
        ),
        default=LEVEL_NONE,
        min=LEVEL_NONE,
        max=LEVEL_ERROR,
        options={'SKIP_SAVE'},
    )
    wm.mixar_pane_message_serial = IntProperty(
        name="Pane Message Serial",
        description=(
            "Bumped on every pane-message write, a repeat of the same text "
            "included, so the painter can tell 'said again' from 'still "
            "showing'"
        ),
        default=0,
        min=0,
        update=_redraw_bubbles,
        options={'SKIP_SAVE'},
    )


def unregister():
    for name in PROP_NAMES:
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)

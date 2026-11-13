# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Bubble window detection and the safe window for a native file read.

A native read (``wm.open_mainfile`` / ``wm.recover_auto_save``) frees the
outgoing Main; a live Agent Bubble window at that moment is a use-after-free
(backend#1914). Every reader therefore asks ``prepare_file_read_window`` for
its context window, which purges the bubbles first, verifies none survived and
only then picks the document window. Kept free of the lifecycle's imports so
the checkpoint and recovery paths (and their tests) can load it on its own.
"""

import bpy


class FileReadContextError(RuntimeError):
    """A native file read is unsafe in the current window context.

    ``reason`` is ``bubble_open`` (a bubble window survived the purge),
    ``no_window_manager`` or ``no_document_window``."""

    def __init__(self, reason: str):
        super().__init__(f"file read refused: {reason}")
        self.reason = reason


def is_agent_bubble_window(window) -> bool:
    """Return True when a Blender window contains the runtime bubble UI."""
    try:
        screen = window.screen
        return screen is not None and any(
            area.type == 'AGENT_BUBBLE' for area in getattr(screen, "areas", ())
        )
    except ReferenceError:
        return False


def document_window(wm=None):
    """The first live, non-temporary window that is not an Agent Bubble.

    Windows without a screen (opening or closing) and stale wrappers are
    skipped, never fatal: the document window is usable regardless."""
    wm = wm if wm is not None else bpy.context.window_manager
    if wm is None:
        return None
    for window in wm.windows:
        try:
            screen = window.screen
            if screen is None or getattr(screen, "is_temporary", False):
                continue
        except ReferenceError:
            continue
        if is_agent_bubble_window(window):
            continue
        return window
    return None


def prepare_file_read_window():
    """Purge the bubble windows, verify the purge, return the read's window.

    Raises ``FileReadContextError`` instead of falling back to another
    context; purge exceptions propagate. The window is picked AFTER the purge
    so the read never runs in a window the purge just freed."""
    from .bubble_lifecycle import close_restored_agent_bubble_windows

    if bpy.context.window_manager is None:
        raise FileReadContextError("no_window_manager")
    close_restored_agent_bubble_windows()
    wm = bpy.context.window_manager
    if wm is None:
        raise FileReadContextError("no_window_manager")
    if any(is_agent_bubble_window(window) for window in wm.windows):
        raise FileReadContextError("bubble_open")
    window = document_window(wm)
    if window is None:
        raise FileReadContextError("no_document_window")
    return window

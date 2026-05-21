# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
UI components for status display in Mixie Chat.

Provides reusable drawing functions for connection status,
error boxes, and streaming text.
"""

from typing import Optional

from ...constants import SessionState, STATE_LABELS


def draw_connection_status(
    layout,
    state: SessionState,
    is_connecting: bool = False,
) -> None:
    """
    Draw connection status indicator.

    Args:
        layout: Blender UI layout
        state: Current session state
        is_connecting: Whether currently attempting to connect
    """
    row = layout.row(align=True)

    if state == SessionState.IDLE:
        row.label(text="", icon='CHECKMARK')  # Connected
        row.label(text="Connected")
    elif state == SessionState.CONNECTING or is_connecting:
        row.label(text="", icon='SORTTIME')  # Connecting
        row.label(text="Connecting...")
    elif state == SessionState.OFFLINE:
        row.label(text="", icon='CANCEL')  # Offline
        row.label(text="Offline")
    elif state == SessionState.BUSY:
        row.label(text="", icon='SORTTIME')
        row.label(text="Busy")
    elif state == SessionState.MODIFYING:
        row.label(text="", icon='GREASEPENCIL')
        row.label(text="Modifying")
    elif state == SessionState.AWAITING_INPUT:
        row.label(text="", icon='QUESTION')
        row.label(text="Awaiting Input")
    else:
        row.label(text="", icon='BLANK1')
        row.label(text=STATE_LABELS.get(state, "Unknown"))


def draw_error_box(
    layout,
    error_message: str,
    show_retry: bool = False,
    retry_operator: Optional[str] = None,
) -> None:
    """
    Draw an error message box.

    Args:
        layout: Blender UI layout
        error_message: Error message to display
        show_retry: Whether to show retry button
        retry_operator: Optional operator ID for retry button
    """
    box = layout.box()
    box.alert = True

    col = box.column(align=True)
    col.label(text="Error", icon='ERROR')

    # Word wrap long error messages
    words = error_message.split()
    line = ""
    for word in words:
        if len(line) + len(word) + 1 > 40:
            col.label(text=line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        col.label(text=line)

    if show_retry and retry_operator:
        box.operator(retry_operator, text="Retry", icon='FILE_REFRESH')


def draw_status_message(
    layout,
    state: SessionState,
    status_message: Optional[str] = None,
) -> None:
    """
    Draw a status message based on current state.

    Args:
        layout: Blender UI layout
        state: Current session state
        status_message: Optional custom status message
    """
    message = status_message or STATE_LABELS.get(state, "")

    if state == SessionState.OFFLINE:
        layout.label(text=message, icon='ERROR')
    else:
        layout.label(text=message)

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene and turn builders shared by the turn-checkpoint suites."""

from types import SimpleNamespace


def _scene(session_id="sess-1", users=1):
    messages = [SimpleNamespace(sender="USER", text=f"m{i}") for i in range(users)]
    return SimpleNamespace(name="Scene", mixie_session_id=session_id, mixie_checkpoint_session_id="",
                           mixie_chat_messages=messages, mixie_chat_user_has_engaged=True)


def _send(scene, text="next"):
    """What a send does after the capture: the chat gains the user message."""
    scene.mixie_chat_messages.append(SimpleNamespace(sender="USER", text=text))


def _turns(tc, scene, n, start=0):
    """Capture-and-send ``n`` turns, each with different document bytes."""
    records = []
    for i in range(start, start + n):
        tc.document["bytes"] = f"before-turn-{i + 1}".encode()
        records.append(tc.m.capture(scene, f"turn {i + 1}"))
        tc.m.bind_request(records[-1], f"cmd-{i + 1}")
        _send(scene, f"turn {i + 1}")
    tc.document["bytes"] = b"tip"
    return records


def _edit(tc, stamp="edited"):
    """A user action: the undo stack (and so the stamp) moves on."""
    tc.bpy.context.window_manager.mixie_chat_undo_stamp = stamp

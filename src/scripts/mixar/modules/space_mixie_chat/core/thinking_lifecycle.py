# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure live->finalized thinking lifecycle for the agent chat.

No bpy imports — operates on any duck-typed bubble exposing `ephemeral`,
`thinking_text`, `thinking_active`, `thinking_start_time` and
`thinking_duration_ms`, so the transition logic is unit-testable outside
Blender. The slot processor wraps this with the real PropertyGroup.

Lifecycle: ephemeral set/append starts a live thinking phase (the C++ side
renders the ephemeral FIFO bubble while `thinking_active`). The backend ends
reasoning with `ephemeral: {clear}` — that snapshot becomes the finalized
"Thought for Ns" dropdown (`thinking_text` + `thinking_duration_ms`).
Multiple phases on one bubble append text and accumulate duration.
"""


def apply_ephemeral_to_bubble(bubble, ephemeral_data: dict, now: float) -> bool:
    """Apply one ephemeral slot op and drive the thinking lifecycle.

    Args:
        bubble: duck-typed message (see module docstring for fields).
        ephemeral_data: dict with one of "set" / "append" / "clear".
        now: current wall-clock time in seconds (injected for testability).

    Returns:
        True when this op finalized a live thinking phase (the caller should
        force a layout rebuild so the new dropdown gets vertical space).
    """
    if ephemeral_data.get("clear"):
        finalized = False
        if bubble.thinking_active and bubble.ephemeral:
            snapshot = bubble.ephemeral
            if bubble.thinking_text:
                bubble.thinking_text = bubble.thinking_text + "\n\n" + snapshot
            else:
                bubble.thinking_text = snapshot
            elapsed = max(0.0, now - bubble.thinking_start_time)
            bubble.thinking_duration_ms = (
                bubble.thinking_duration_ms + int(elapsed * 1000)
            )
            finalized = True
        bubble.thinking_active = False
        bubble.thinking_start_time = 0.0
        bubble.ephemeral = ""
        return finalized

    if "set" in ephemeral_data:
        bubble.ephemeral = ephemeral_data["set"] or ""
    elif "append" in ephemeral_data:
        bubble.ephemeral += ephemeral_data["append"] or ""

    if bubble.ephemeral and not bubble.thinking_active:
        bubble.thinking_active = True
        bubble.thinking_start_time = now
    return False

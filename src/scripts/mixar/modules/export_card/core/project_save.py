# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixar project / Blender file: a copy of the open document.

``save_as_mainfile(copy=True)`` writes the new file without changing which
file is open. Removing the agent chat reuses the "Export .blend without chat
history" helpers (snapshot, strip, restore — the working file always gets its
chat back, even when the save fails). The copy skips the file thumbnail (an
EEVEE camera render that held the save for seconds on a heavy scene) and keeps
the Agent island open (`keep_windows_for_snapshot`)."""

from __future__ import annotations

import os
from contextlib import nullcontext

import bpy


def _keep_windows():
    try:
        from mixar.modules.agent_bubble.core.bubble_lifecycle import keep_windows_for_snapshot
        return keep_windows_for_snapshot()
    except Exception:  # noqa: BLE001 - a build without the island
        return nullcontext()


def save_copy(path: str, strip_chat: bool, compress: bool) -> dict:
    """Write the copy; ``{"success", "dropped", "size", "error"}``."""
    from mixar.modules.space_mixie_chat.ui.operators import export_ops as chat_export
    scenes = list(bpy.data.scenes)
    snapshot = chat_export._snapshot_chat(scenes) if strip_chat else None
    dropped = chat_export._strip_chat(scenes) if strip_chat else 0
    try:
        with _keep_windows():
            bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, compress=bool(compress),
                                        check_existing=False, thumbnail=False)
    except Exception as exc:  # noqa: BLE001 - reported on the card
        from mixar.modules.space_mixie_chat.core.agent_export import scrub_error
        return {"success": False, "dropped": dropped, "size": 0, "error": scrub_error(exc)}
    finally:
        if snapshot is not None:
            chat_export._restore_chat(snapshot)
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return {"success": True, "dropped": dropped, "size": size, "error": ""}

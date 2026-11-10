# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The project file a published game carries so others can remix it.

``prepare`` (main thread) captures a copy of the open file the same way the
material bake does: an unmodified file on disk is copied by the worker,
anything else is written with a ``copy=True`` save. ``stage`` (worker) then
runs a BACKGROUND Mixar on that copy (``source_child.py``, scripts
disabled) to remove the creator's agent conversation, session ids and
store identity, and saves it compressed. Only that cleaned file is ever
uploaded. If anything here fails the game still publishes, without a source.
"""

from __future__ import annotations

import os
import shutil
import uuid

from mixar.modules.game_studio.core import godot_runner

from ..constants import SOURCE_DIRNAME, SOURCE_RESULT_SCHEMA, SOURCE_TIMEOUT_S

CHILD_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "source_child.py")


def prepare(game_dir: str, slug: str) -> dict:
    """Main thread. Returns the plain ``source`` context the worker needs."""
    import bpy
    folder = os.path.join(game_dir, SOURCE_DIRNAME, uuid.uuid4().hex[:12])
    os.makedirs(folder, exist_ok=True)
    copy = os.path.join(folder, f"{slug or 'game'}.mixar")
    on_disk = bpy.data.filepath
    if bpy.data.is_dirty or not on_disk or not os.path.isfile(on_disk):
        on_disk = ""
        try:
            from mixar.modules.agent_bubble.core.bubble_lifecycle import keep_windows_for_snapshot
        except Exception:  # noqa: BLE001 — headless builds have no bubble
            from contextlib import nullcontext as keep_windows_for_snapshot
        with keep_windows_for_snapshot():
            bpy.ops.wm.save_as_mainfile(filepath=copy, copy=True, thumbnail=False)
    return {"folder": folder, "copy": copy, "source": on_disk, "binary": bpy.app.binary_path,
            "result": os.path.join(folder, "result.json")}


def discard(source: dict) -> None:
    shutil.rmtree((source or {}).get("folder") or "", ignore_errors=True)


def stage(source: dict, cancel=None, runner=godot_runner.run) -> str:
    """Worker thread. The cleaned file's path, or "" when it could not be
    made (the caller publishes without a source)."""
    try:
        if source.get("source"):
            shutil.copyfile(source["source"], source["copy"])
        # -Y: never auto-run the file's own scripts in the cleaning process.
        result = runner(source["binary"], ["-Y", "-b", source["copy"], "-noaudio", "--python",
                                           CHILD_SCRIPT, "--"],
                        source["result"], "remix_source", cancel=cancel, timeout=SOURCE_TIMEOUT_S,
                        schema=SOURCE_RESULT_SCHEMA)
    except OSError:
        return ""
    if not result.get("ok") or not os.path.isfile(source["copy"]):
        return ""
    return source["copy"]

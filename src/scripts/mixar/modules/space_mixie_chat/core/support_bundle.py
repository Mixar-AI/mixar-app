# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One zip with what a bug report needs from this machine.

Contents (all under ``~/.mixar`` unless noted):

- ``logs/``: the client log files and their rotations
  (``config/logging_config.py``): WARNING and above from every module plus the
  ``[SCENES]`` ledger at INFO, UTC timestamps.
- ``scenes-dossier/<session>/events.jsonl``: the per-session scene ledger.
- ``checkpoints/<session>/index.json``: the turn-checkpoint records. The
  ``.mixar`` snapshots are whole documents and are NOT bundled.
- ``scenes.json``: the scene table at bundle time (name, chat session and
  state, object count, world and camera names).
- ``app.json``: versions, platform, the open file's basename and the UTC time,
  so a client log line can be aligned with a backend trace.

No scene geometry, images or chat transcripts. Log lines are free text and can
name files or objects; the user picks where the zip goes and whether to send it.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import zipfile
from datetime import datetime, timezone

from mixar.config.logging_config import get_logger, log_dir

from .checkpoint_store import checkpoints_root

logger = get_logger(__name__)

_INDEX_FILENAME = "index.json"
#: The log folder and dossiers are bounded already (rotation, prune); the cap
#: only keeps a runaway file from making an unsendable zip.
MAX_FILE_BYTES = 32 * 1024 * 1024


def dossier_root() -> str:
    from mixar.modules.common.scenes_log import dossier_root as _root
    return _root()


def _iter_files(root: str, *, only_name: str | None = None):
    """``(absolute path, archive path)`` for every regular file under ``root``."""
    if not root or not os.path.isdir(root):
        return
    base = os.path.basename(os.path.normpath(root))
    for folder, _dirs, files in os.walk(root):
        for name in sorted(files):
            if only_name and name != only_name:
                continue
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            rel = os.path.relpath(path, root)
            yield path, os.path.join(base, rel).replace(os.sep, "/")


def _name_of(datablock) -> str:
    return str(getattr(datablock, "name", "") or "") if datablock is not None else ""


def scene_table() -> list[dict]:
    """One row per scene (main thread; never raises)."""
    try:
        import bpy
        scenes = list(bpy.data.scenes)
    except Exception:  # noqa: BLE001
        return []
    rows = []
    for scene in scenes:
        row = {"name": "?"}
        try:
            row["name"] = str(scene.name)
            row["session"] = str(getattr(scene, "mixie_session_id", "") or "")
            row["state"] = str(getattr(scene, "mixie_chat_state", "") or "")
            row["objects"] = len(scene.objects)
            row["world"] = _name_of(scene.world)
            row["camera"] = _name_of(scene.camera)
        except Exception:  # noqa: BLE001
            pass
        rows.append(row)
    return rows


def app_info() -> dict:
    info = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
    }
    try:
        import bpy
        info["blender_version"] = ".".join(str(v) for v in bpy.app.version)
        info["version_string"] = str(bpy.app.version_string)
        info["document"] = os.path.basename(bpy.data.filepath or "") or "(unsaved)"
        window = getattr(bpy.context, "window", None)
        info["window_scene"] = _name_of(window.scene) if window is not None else ""
    except Exception:  # noqa: BLE001
        pass
    try:
        from mixar.modules.common.updates.core.update_checker import get_runtime_version
        info["mixar_version"] = get_runtime_version() or ""
    except Exception:  # noqa: BLE001
        pass
    return info


def build_support_bundle(destination: str, *, logs: str | None = None,
                         dossier: str | None = None, checkpoints: str | None = None,
                         scenes: list[dict] | None = None,
                         info: dict | None = None) -> dict:
    """Write the zip at ``destination`` and return a manifest of what went in.

    The folders default to the app's own; tests pass their own.
    """
    logs = log_dir() if logs is None else logs
    dossier = dossier_root() if dossier is None else dossier
    checkpoints = checkpoints_root() if checkpoints is None else checkpoints
    scenes = scene_table() if scenes is None else scenes
    info = app_info() if info is None else info
    manifest = {"files": [], "skipped": [], "scenes": len(scenes)}
    os.makedirs(os.path.dirname(os.path.abspath(destination)) or ".", exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, arc in [
            *_iter_files(logs),
            *_iter_files(dossier),
            *_iter_files(checkpoints, only_name=_INDEX_FILENAME),
        ]:
            try:
                if os.path.getsize(path) > MAX_FILE_BYTES:
                    manifest["skipped"].append(arc)
                    continue
                zf.write(path, arc)
                manifest["files"].append(arc)
            except OSError:
                manifest["skipped"].append(arc)
        zf.writestr("scenes.json", json.dumps(scenes, indent=1, default=str))
        zf.writestr("app.json", json.dumps(info, indent=1, default=str))
        manifest["files"].extend(["scenes.json", "app.json"])
        zf.writestr("manifest.json", json.dumps(manifest, indent=1))
    return manifest

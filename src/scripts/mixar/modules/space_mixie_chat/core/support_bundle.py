# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One zip with everything a scene-tab bug report needs.

What goes in (all under ``~/.mixar`` unless noted):

- ``logs/``: the client log file and its rotations
  (``config/logging_config.py``): WARNING+ from every module plus the
  ``[SCENES]`` ledger at INFO, UTC timestamps.
- ``scenes-dossier/<session>/events.jsonl``: the per-session scene ledger.
- ``checkpoints/<session>/index.json``: the turn-checkpoint records (which
  snapshot was taken when). The ``.mixar`` snapshots themselves are whole
  documents and are NOT bundled; the index says which file to ask for.
- ``scenes.json``: the live scene table at bundle time — every scene's name,
  session id, object count, world, camera and custom keys — the same fields
  the ``scene.added`` audit line carries.
- ``app.json``: versions, platform, the open file's basename and the UTC
  time, so a console clock can be aligned with a backend trace.

Nothing in the bundle is a filesystem path except the bundle's own
manifest of what it contains; the open document is reported by basename.
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
#: The dossier and the log folder are bounded already (rotation, prune); the
#: cap only keeps a runaway folder from making an unsendable zip.
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


def scene_table() -> list[dict]:
    """Every scene as the audit sees it (main-thread bpy read; never raises)."""
    try:
        import bpy
        from .scene_identity import describe_scene
    except Exception:  # noqa: BLE001
        return []
    rows = []
    try:
        scenes = list(bpy.data.scenes)
    except Exception:  # noqa: BLE001
        return rows
    for scene in scenes:
        row = {"name": "?", "session": ""}
        try:
            row["name"] = str(scene.name)
            row["session"] = str(getattr(scene, "mixie_session_id", "") or "")
            row["state"] = str(getattr(scene, "mixie_chat_state", "") or "")
            row.update(describe_scene(scene))
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
        info["window_scene"] = str(window.scene.name) if window is not None and window.scene else ""
    except Exception:  # noqa: BLE001
        pass
    try:
        from mixar.modules.common.updates.core.update_checker import get_runtime_version
        info["mixar_version"] = get_runtime_version() or ""
    except Exception:  # noqa: BLE001
        pass
    return info


def build_support_bundle(destination: str, *, logs: str | None = None, dossier: str | None = None,
                         checkpoints: str | None = None, scenes: list[dict] | None = None,
                         info: dict | None = None) -> dict:
    """Write the zip at ``destination``. Returns a manifest of what went in.
    The folders default to the app's own; tests pass their own."""
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

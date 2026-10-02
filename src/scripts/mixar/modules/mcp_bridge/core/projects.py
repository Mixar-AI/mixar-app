# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Recent Mixar projects for MCP clients: listed by name, opened by id.

Main thread only (the UI-control pump runs these). The model never sends or
receives a path: an entry's id is a digest of a recent-files path, resolved
again from the same list when opening. Opening refuses while the current
document is still working (an agent turn, an MCP scene operation, a render, or
a generation job whose result would import into a scene that is about to
close), and, unless told to save or discard, while it has unsaved changes.
"""

from datetime import datetime, timezone
import hashlib
from pathlib import Path

import bpy

from mixar.modules.common.ui_control.constants import UIError
from . import scene_tabs

PROJECT_SUFFIXES = (".mixar", ".blend")
MAX_PROJECTS = 20
UNSAVED_CHOICES = ("refuse", "save", "discard")


def _recent_paths() -> list:
    """Blender's recent-files history, newest first, existing project files only."""
    history = Path(bpy.utils.user_resource('CONFIG')) / "recent-files.txt"
    try:
        lines = history.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found, seen = [], set()
    for line in (line.strip() for line in lines):
        if not line or line in seen:
            continue
        seen.add(line)
        path = Path(line)
        if path.suffix.lower() in PROJECT_SUFFIXES and path.is_file():
            found.append(path)
            if len(found) == MAX_PROJECTS:
                break
    return found


def _project_id(path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]


def _is_current(path) -> bool:
    return bool(bpy.data.filepath) and Path(bpy.data.filepath) == Path(path)


def _entry(path) -> dict:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return {"project": _project_id(path), "name": path.stem, "folder": path.parent.name,
            "modified": modified.isoformat(timespec="minutes"), "current": _is_current(path)}


def list_projects() -> dict:
    return {"projects": [_entry(path) for path in _recent_paths()],
            "current_file_saved": bool(bpy.data.filepath),
            "current_unsaved_changes": bool(bpy.data.is_dirty)}


def _still_working() -> str:
    """Why closing the current document now would cut into work, or ''."""
    from mixar.modules.common.job_queue.core.queue_manager import active_job_count
    from mixar.modules.space_mixie_chat.constants import SessionState, is_lane_scene
    from . import lease
    if lease.any_active_operation():
        return "an MCP scene operation is still running"
    session = scene_tabs._session()
    for scene in bpy.data.scenes:
        if is_lane_scene(scene):
            return "a Mixar agent task is still running"
        if session.get_state(scene) not in (SessionState.IDLE, SessionState.OFFLINE) or session.run_open(scene):
            return "the Mixar agent is working in scene tab %r" % scene.name
    if active_job_count():
        return "generation jobs are still running and would import into a scene that closes"
    return ""


def _resolve(project: str):
    matches = [path for path in _recent_paths() if _project_id(path) == project]
    if len(matches) != 1:
        raise UIError("project_unavailable", "No recent project has that id; list them with mixar_projects")
    return matches[0]


def preflight(args: dict):
    """Every refusal comes before the call is claimed (a clean "failed" receipt)."""
    scene_tabs._gate()
    path = _resolve(args["project"])
    if _is_current(path):
        return path
    reason = _still_working()
    if reason:
        raise UIError("document_busy", "Not opened: %s. Wait for it to finish, then try again" % reason)
    unsaved = args.get("unsaved", "refuse")
    if bpy.data.is_dirty and unsaved == "refuse":
        raise UIError("unsaved_changes", "The open file has unsaved changes. Ask the user whether to save or "
                      "discard them, then call again with unsaved='save' or unsaved='discard'")
    if bpy.data.is_dirty and unsaved == "save" and not bpy.data.filepath:
        raise UIError("unsaved_untitled", "The open file has never been saved, so it cannot be saved here. Ask "
                      "the user to save it in Mixar, or call again with unsaved='discard' if they agree to lose it")
    return path


def open_project(path, unsaved: str = "refuse") -> dict:
    """Open ``path`` as returned by preflight (the caller claims the call in between)."""
    opened = not _is_current(path)
    if opened:
        if bpy.data.is_dirty and unsaved == "save":
            if "FINISHED" not in bpy.ops.wm.save_mainfile():
                raise UIError("save_failed", "Mixar could not save the open file; nothing was opened")
        # No context override: the window it would name is freed by the load.
        if "FINISHED" not in bpy.ops.wm.open_mainfile(filepath=str(path)):
            raise UIError("open_failed", "Mixar could not open that project")
    from mixar.modules.space_mixie_chat.core.scene_identity import adopt_scene
    scene = scene_tabs._shown()
    adopt_scene(scene)  # A loaded document is ready once connected, not OFFLINE.
    shown = scene_tabs._entry(scene, scene)
    return {"project": _project_id(path), "name": path.stem, "opened": opened,
            "scene": shown["name"], "session": shown["session"],
            "scenes": scene_tabs.list_scenes()["scenes"]}

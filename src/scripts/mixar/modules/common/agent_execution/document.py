# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stable document / scene identity and the document epoch.

- ``document_id``: a UUID stored as a custom property on the first scene
  datablock (``scene['mixar_document_id']``) — survives save/load, but is
  NOT undo-safe on its own, which is why the epoch exists.
- ``scene_id``: a per-scene UUID custom property.
- ``document_epoch``: a module-global monotonic counter bumped on file load,
  undo and redo. It lives OUTSIDE undo-restored data, so a commit prepared
  against epoch N can never be published after the user undid past it.
- ``mixie_v3_run_active`` (WindowManager BoolProperty): while a v3 run is
  active the viewport lock stands down and manual edits keep being captured.
"""

from __future__ import annotations

import uuid
from typing import Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

DOCUMENT_ID_PROP = "mixar_document_id"
SCENE_ID_PROP = "mixar_scene_id"
WM_RUN_ACTIVE_PROP = "mixie_v3_run_active"

_document_epoch: int = 0
_commit_in_progress: bool = False
_registered = False


def document_epoch() -> int:
    return _document_epoch


def bump_document_epoch(reason: str = "") -> int:
    global _document_epoch
    _document_epoch += 1
    logger.debug("document epoch -> %s (%s)", _document_epoch, reason)
    return _document_epoch


def _bpy():
    import bpy

    return bpy


def _first_scene(bpy=None):
    bpy = bpy or _bpy()
    try:
        scenes = bpy.data.scenes
        for s in scenes:
            return s
    except Exception:
        pass
    try:
        return bpy.context.scene
    except Exception:
        return None


def _ensure_prop(datablock, key: str) -> Optional[str]:
    """Return the datablock's UUID custom prop, creating it if absent."""
    if datablock is None:
        return None
    try:
        value = datablock.get(key)
    except Exception:
        value = None
    if isinstance(value, str) and value:
        return value
    value = str(uuid.uuid4())
    try:
        datablock[key] = value
    except Exception:
        return None
    return value


def ensure_document_id(bpy=None) -> Optional[str]:
    return _ensure_prop(_first_scene(bpy), DOCUMENT_ID_PROP)


def ensure_scene_id(scene) -> Optional[str]:
    return _ensure_prop(scene, SCENE_ID_PROP)


def document_identity(scene=None, bpy=None) -> dict:
    """Identity block returned on activate and checked on commit."""
    bpy = bpy or _bpy()
    if scene is None:
        try:
            scene = bpy.context.scene
        except Exception:
            scene = None
    return {
        "document_id": ensure_document_id(bpy),
        "document_epoch": document_epoch(),
        "scene_id": ensure_scene_id(scene),
        "scene_name": getattr(scene, "name", "") if scene is not None else "",
    }


# --- run-active flag ---------------------------------------------------------

def run_active() -> bool:
    """True only when the WindowManager flag is literally True.

    An unregistered property (older add-on state, or a stubbed bpy in tests)
    must read as "no v3 run", never as truthy.
    """
    try:
        wm = _bpy().context.window_manager
        return getattr(wm, WM_RUN_ACTIVE_PROP, False) is True if wm else False
    except Exception:
        return False


def set_run_active(flag: bool) -> None:
    try:
        wm = _bpy().context.window_manager
        if wm is not None:
            setattr(wm, WM_RUN_ACTIVE_PROP, bool(flag))
    except Exception:
        logger.debug("could not set %s", WM_RUN_ACTIVE_PROP, exc_info=True)


def commit_in_progress() -> bool:
    return _commit_in_progress


# --- foreground tasks --------------------------------------------------------
#
# A FOREGROUND-class task (texturing an existing object, lighting, editing
# existing geometry) runs its scripts on THIS Blender, routed to the chat
# session's scene, serialized by the backend. While any is active the viewport
# lock and manual-capture suppression stand up exactly as for a legacy turn;
# worker-class tasks never touch this document and keep the v3 unlock.
_foreground_tasks: set = set()   # {(run_id, task_id)}


def foreground_tasks_active() -> int:
    return len(_foreground_tasks)


def set_foreground_task(run_id: str, task_id: str, active: bool) -> int:
    key = (str(run_id), str(task_id))
    if active:
        _foreground_tasks.add(key)
    else:
        _foreground_tasks.discard(key)
    return len(_foreground_tasks)


def clear_foreground_tasks(run_id: Optional[str] = None) -> int:
    """Drop every foreground flag (or only ``run_id``'s). Returns what remains."""
    if run_id is None:
        _foreground_tasks.clear()
    else:
        for key in [k for k in _foreground_tasks if k[0] == str(run_id)]:
            _foreground_tasks.discard(key)
    return len(_foreground_tasks)


class commit_scope:
    """Marks the short foreground publish so history attributes it to the agent."""

    def __enter__(self):
        global _commit_in_progress
        _commit_in_progress = True
        return self

    def __exit__(self, *exc):
        global _commit_in_progress
        _commit_in_progress = False
        return False


# --- registration ------------------------------------------------------------

def _on_load_post(*_):
    bump_document_epoch("load_post")


def _on_undo_post(*_):
    bump_document_epoch("undo_post")


def _on_redo_post(*_):
    bump_document_epoch("redo_post")


def register() -> None:
    global _registered
    # Reconcile the live lists even after initial setup: an add-on reload or
    # external handler cleanup can remove one while this module stays loaded.
    bpy = _bpy()
    try:
        from bpy.props import BoolProperty

        if not hasattr(bpy.types.WindowManager, WM_RUN_ACTIVE_PROP):
            setattr(
                bpy.types.WindowManager, WM_RUN_ACTIVE_PROP,
                BoolProperty(name="Mixie v3 run active", default=False,
                             options={"SKIP_SAVE"}),
            )
    except Exception:
        logger.debug("WM prop registration skipped", exc_info=True)
    handlers = bpy.app.handlers
    for name, fn in (("load_post", _on_load_post), ("undo_post", _on_undo_post),
                     ("redo_post", _on_redo_post)):
        try:
            lst = getattr(handlers, name)
            # Mark the existing function in place, keeping import-time bpy
            # access out of this shared module. Blender otherwise drops all
            # three callbacks before dispatching load_post for a new file.
            handlers.persistent(fn)
            if fn not in lst:
                lst.append(fn)
        except Exception:
            logger.debug("handler %s registration skipped", name, exc_info=True)
    _registered = True


def unregister() -> None:
    global _registered
    if not _registered:
        return
    bpy = _bpy()
    handlers = bpy.app.handlers
    for name, fn in (("load_post", _on_load_post), ("undo_post", _on_undo_post),
                     ("redo_post", _on_redo_post)):
        try:
            lst = getattr(handlers, name)
            if fn in lst:
                lst.remove(fn)
        except Exception:
            pass
    try:
        if hasattr(bpy.types.WindowManager, WM_RUN_ACTIVE_PROP):
            delattr(bpy.types.WindowManager, WM_RUN_ACTIVE_PROP)
    except Exception:
        pass
    _registered = False

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Attach / detach single files on a scene's chat: the "Attached files" set.

Any file that is neither an image pill nor an imported model (a video, a
PDF, a text note, audio…) becomes a persistent context-file chip. All of a
scene's files form ONE synthetic folder on the wire, ``ATTACHED_FILES_LABEL``,
whose id is ``scene.mixie_context_files_id``; the registry serves it as a
``FileSet`` so every ``context_folder.*`` RPC works on it unchanged.
Main thread only (scene properties).
"""

import os
import uuid
from pathlib import Path

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ..constants import MAX_CONTEXT_FILES
from .errors import ContextFolderError
from .paths import file_kind, ignored_part
from .registry import get_registry

_logger = get_logger(__name__)


def attached_files(scene) -> list:
    """``[(file_id, name, kind)]`` attached to this scene's chat, in order."""
    items = getattr(scene, "mixie_context_files", None) or ()
    return [(item.file_id, item.name, item.kind) for item in items if getattr(item, "file_id", "")]


def publish_set(scene) -> str:
    """Publish the scene's current members to the registry; returns the set
    id, or "" when no file is attached. A scene that once had files keeps its
    id, so its now-EMPTY membership is published too: the registry must never
    keep serving a detached file under a set id a session still holds."""
    set_id = str(getattr(scene, "mixie_context_files_id", "") or "")
    members = attached_files(scene)
    if set_id:
        get_registry().publish_file_set(set_id, [(name, file_id) for file_id, name, _ in members])
    return set_id if members else ""


def unique_file_name(name: str, used) -> str:
    """``clip.mp4`` → ``clip (2).mp4`` while the name is taken: the chip label
    and the folder-relative path the agent writes."""
    stem, suffix = os.path.splitext(name)
    candidate, count = name, 1
    while candidate in used:
        count += 1
        candidate = f"{stem} ({count}){suffix}"
    return candidate


def attach_file(scene, filepath: str, *, origin: str = "picker") -> dict:
    """Attach one regular file to the scene's chat; idempotent for the same
    resolved path. ``error`` is an untranslated, path-free ``n_`` template the
    caller translates for display; ``error_args`` fills it."""
    try:
        if not filepath or not os.path.isfile(filepath):
            raise ContextFolderError("not_a_file", n_("Choose a file to attach"))
        path = Path(filepath).resolve(strict=True)
        if ignored_part(path.name):
            raise ContextFolderError("hidden_file", n_("Hidden files are not shared"))
        file_id = get_registry().register_file(path)
    except (ContextFolderError, OSError) as exc:
        message = exc.message if isinstance(exc, ContextFolderError) else n_("That file cannot be read")
        return {"success": False, "error": message, "error_args": {}}
    files = scene.mixie_context_files
    for item in files:
        if item.file_id == file_id:
            return {"success": True, "file_id": file_id, "name": item.name, "kind": item.kind, "already": True}
    if len(files) >= MAX_CONTEXT_FILES:
        return {"success": False, "error": n_("At most {count} files can be attached to a chat"),
                "error_args": {"count": MAX_CONTEXT_FILES}}
    if not getattr(scene, "mixie_context_files_id", ""):
        scene.mixie_context_files_id = str(uuid.uuid4())
    item = files.add()
    item.file_id = file_id
    item.name = unique_file_name(path.name, {existing.name for existing in files if existing is not item})
    item.kind = file_kind(path.name)
    item.origin = origin  # a re-attach keeps the first origin: a picker chip never turns board-owned
    publish_set(scene)
    _logger.debug("context file attached from %s: %s (%s)", origin, item.name, item.kind)
    return {"success": True, "file_id": file_id, "name": item.name, "kind": item.kind, "already": False}


def detach_file(scene, file_id: str) -> bool:
    """Remove the file from this scene's chat. The membership the registry
    serves shrinks at once — to nothing when the last file goes — so a running
    agent's next read of that name is ``not_found``. The set id and the
    session's grant stay for the life of the scene; an empty set exposes
    nothing."""
    files = scene.mixie_context_files
    for index, item in enumerate(files):
        if item.file_id == file_id:
            files.remove(index)
            publish_set(scene)
            return True
    return False

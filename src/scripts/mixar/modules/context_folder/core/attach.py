# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Attach / detach a folder on a scene's chat, and stamp it on a Send.

Main thread only (scene properties). The operators and the turn transport
are thin wrappers over these three functions.
"""

import os
from pathlib import Path

from mixar.modules.common.i18n import n_

from ..constants import MAX_FOLDERS
from . import grants
from .errors import ContextFolderError
from .manifest import attached_folders, build_folder_context
from .registry import get_registry


def attach_folder(scene, directory: str) -> dict:
    """Attach ``directory`` to the scene's chat; idempotent for a folder that
    is already attached. ``error`` is an untranslated, path-free template
    (``n_``) the caller translates for display; ``error_args`` fills it."""
    try:
        if not directory or not os.path.isdir(directory):
            raise ContextFolderError("not_a_folder", n_("Choose a folder to attach"))
        root = Path(directory).resolve(strict=True)
        if root.parent == root:
            raise ContextFolderError("drive_root", n_("Attach a project folder, not a whole drive"))
        folder_id = get_registry().register(root)
    except (ContextFolderError, OSError) as exc:
        message = exc.message if isinstance(exc, ContextFolderError) else n_("That folder cannot be read")
        return {"success": False, "error": message, "error_args": {}}
    folders = scene.mixie_context_folders
    for item in folders:
        if item.folder_id == folder_id:
            return {"success": True, "folder_id": folder_id, "name": item.name, "already": True}
    if len(folders) >= MAX_FOLDERS:
        return {"success": False, "error": n_("At most {count} folders can be attached to a chat"),
                "error_args": {"count": MAX_FOLDERS}}
    item = folders.add()
    item.folder_id = folder_id
    item.name = root.name or "folder"
    return {"success": True, "folder_id": folder_id, "name": item.name, "already": False}


def detach_folder(scene, folder_id: str) -> bool:
    """Remove the folder from this scene's chat and revoke the session's
    access at once — a running agent's next read is refused."""
    folders = scene.mixie_context_folders
    for index, item in enumerate(folders):
        if item.folder_id == folder_id:
            folders.remove(index)
            grants.revoke(str(getattr(scene, "mixie_session_id", "") or ""), folder_id)
            return True
    return False


def grant_session(scene, session_id: str) -> None:
    """Grant the session exactly the folders attached to its scene now."""
    grants.grant(session_id, [folder_id for folder_id, _ in attached_folders(scene)])


def folder_context_for_send(scene, session_id: str) -> dict:
    """The turn's ``folder_context``, granting the session exactly these folders."""
    grant_session(scene, session_id)
    return build_folder_context(scene)

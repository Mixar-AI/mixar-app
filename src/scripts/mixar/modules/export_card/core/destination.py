# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where the card writes: the default name and folder, the full path, and
what is wrong with the name or folder the user typed.

The folder defaults to the open project's folder (an ``exports`` folder
beside it), else Downloads; the name to the project's file name, else the
scene's. Both persist on the card for the session, so a second export lands
where the first did. Pure functions take the inputs they need; only
`project_defaults` reads ``bpy``."""

from __future__ import annotations

import os
import re

from mixar.modules.common.i18n import n_

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}
NAME_LIMIT = 120


def clean_stem(value: str, extension: str = "") -> str:
    """A file name with the characters no OS accepts replaced, the extension
    the user may have typed dropped, never empty."""
    stem = _UNSAFE.sub("_", str(value or "")).strip(" .")[:NAME_LIMIT]
    if extension and stem.lower().endswith(extension.lower()):
        stem = stem[: -len(extension)].strip(" .")
    return stem or "export"


def default_stem(blend_path: str, scene_name: str) -> str:
    if blend_path:
        return clean_stem(os.path.splitext(os.path.basename(blend_path))[0])
    return clean_stem(scene_name or "export")


def default_folder(blend_path: str, downloads: str) -> str:
    if blend_path:
        return os.path.join(os.path.dirname(blend_path), "exports")
    return downloads


def full_path(folder: str, stem: str, extension: str) -> str:
    return os.path.join(folder, clean_stem(stem, extension) + extension)


def problem(folder: str, stem: str) -> str:
    """Why the destination cannot be written (a msgid), or ''."""
    if not str(folder or "").strip():
        return n_("Choose a folder to export to.")
    if not os.path.isabs(folder):
        return n_("Choose a full folder path.")
    raw = str(stem or "").strip()
    if not raw:
        return n_("Type a file name.")
    if clean_stem(raw).split(".")[0].upper() in _RESERVED:
        return n_("Windows does not allow this file name. Try another one.")
    parent = folder
    while parent and not os.path.isdir(parent):
        up = os.path.dirname(parent)
        if up == parent:
            break
        parent = up
    if not parent or not os.path.isdir(parent):
        return n_("This folder's drive is not available.")
    if not os.access(parent, os.W_OK):
        return n_("Mixar cannot write to this folder. Choose another one.")
    return ""


def exists(folder: str, stem: str, extension: str) -> bool:
    return bool(extension) and os.path.exists(full_path(folder, stem, extension))


def ensure_folder(folder: str) -> None:
    os.makedirs(folder, exist_ok=True)


def project_defaults() -> tuple[str, str]:
    """(stem, folder) for the open project."""
    import bpy
    from mixar.modules.space_mixie_chat.core.agent_export import resolve_export_folder
    blend = bpy.data.filepath or ""
    scene = bpy.context.scene
    return (default_stem(blend, scene.name if scene else ""),
            default_folder(blend, resolve_export_folder("downloads")))

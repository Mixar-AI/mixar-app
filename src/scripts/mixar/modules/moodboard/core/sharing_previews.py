# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Small Explore cover icons; private data never persists to the project."""
import base64
from pathlib import Path
import tempfile

import bpy.utils.previews

_previews = None
_directory = None


def clear():
    global _previews, _directory
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
    if _directory is not None:
        _directory.cleanup()
        _directory = None


def load_covers(records):
    global _previews, _directory
    clear()
    _previews = bpy.utils.previews.new()
    _directory = tempfile.TemporaryDirectory(prefix='mixar-board-covers-')
    for index, record in enumerate(records):
        cover = record.get('cover', '')
        if not cover or len(cover) > 1024 * 1024:
            continue
        try:
            path = Path(_directory.name) / f'{index}.jpg'
            path.write_bytes(base64.b64decode(cover, validate=True))
            _previews.load(str(index), str(path), 'IMAGE')
        except (ValueError, OSError):
            continue


def icon(index):
    item = _previews.get(str(index)) if _previews else None
    return item.icon_id if item else 0

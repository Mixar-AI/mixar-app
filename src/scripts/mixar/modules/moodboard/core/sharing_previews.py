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


def load_board_cover(scene):
    """Prepare one thumbnail on dialog invocation, never from a draw callback."""
    import io
    from PIL import Image
    from mixar.modules.common.utils.image_utils import image_to_png_bytes
    images = [m.image for m in scene.mixie_moodboard_images if m.image and m.image.source != 'MOVIE']
    images.extend(n.preview_image for n in scene.mixie_moodboard_action_nodes if n.preview_image)
    covers = []
    if images:
        try:
            with Image.open(io.BytesIO(image_to_png_bytes(images[0]))) as source:
                source.thumbnail((480, 320))
                stream = io.BytesIO()
                source.convert('RGB').save(stream, 'JPEG')
                covers.append({'cover': base64.b64encode(stream.getvalue()).decode()})
        except (ValueError, OSError, RuntimeError):
            pass
    load_covers(covers)

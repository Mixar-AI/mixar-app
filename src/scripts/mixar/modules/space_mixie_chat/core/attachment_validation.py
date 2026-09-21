# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Keep movie files and movie datablocks out of the Agent image transport."""

import os

import bpy

from ..constants import VIDEO_FILE_FORMATS


def is_video_attachment(path, source):
    if source == 'FILE':
        # This branch also runs on the image encoder pool: never read bpy here.
        return os.path.splitext(path)[1].lower() in VIDEO_FILE_FORMATS
    if source == 'BLEND_DATA':
        image = bpy.data.images.get(path)
        return image is not None and image.source == 'MOVIE'
    return False


def pending_video_attachments(scene):
    return any(is_video_attachment(att.image_path, att.image_source)
               for att in getattr(scene, 'mixie_chat_pending_attachments', ()))

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Resolve pending chat attachments to the names the backend inlines.

Main thread only (reads and may load ``bpy.data.images``).
"""

import os

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def resolve_attachment_names(pending_attachments) -> tuple[list, list]:
    """(attachment_names, imported_object_names) for a send.

    Returns positional ``attachment_names`` (empty string where an attachment
    did not resolve to a ``bpy.data.images`` entry) and the flat list of
    scene objects that MODEL_FILE attachments imported (#1268). Names only —
    a local path never leaves the add-on.
    """
    # Resolve each attachment to a stable bpy.data.images name. BLEND_DATA
    # attachments already carry the name in image_path; FILE attachments
    # are loaded into bpy.data.images on the main thread (check_existing
    # reuses an entry if one already points at this filepath). Sending the
    # name in the payload lets the backend inline it into the user
    # message, so the agent can pass image_name to generation tools
    # without a get_last_user_message round-trip.
    attachment_names: list = []
    # #1268: MODEL_FILE attachments are NOT images — they are imported
    # scene objects. Their names ride a parallel field so the backend
    # annotates the message without touching the vision gate.
    imported_object_names: list = []
    for att in pending_attachments:
        if att.image_source == 'MODEL_FILE':
            names = [
                n for n in str(att.imported_object_names or "").split(",")
                if n.strip()
            ]
            imported_object_names.extend(names)
            attachment_names.append("")  # keep index alignment
            continue
        resolved_name = ""
        try:
            if att.image_source == 'BLEND_DATA':
                img = bpy.data.images.get(att.image_path)
                if img is not None:
                    resolved_name = img.name
            elif att.image_source == 'FILE':
                # Prefer an existing entry that already points at this file
                for candidate in bpy.data.images:
                    if (
                        candidate.filepath == att.image_path
                        or bpy.path.abspath(candidate.filepath) == att.image_path
                    ):
                        resolved_name = candidate.name
                        break
                if not resolved_name and os.path.isfile(att.image_path):
                    try:
                        img = bpy.data.images.load(att.image_path, check_existing=True)
                        img.colorspace_settings.name = 'sRGB'
                        # Pack so a later move/delete of the source file
                        # doesn't break the agent's reference.
                        try:
                            img.pack()
                        except RuntimeError:
                            pass
                        resolved_name = img.name
                    except RuntimeError as e:
                        logger.warning(f"Could not load attachment {att.image_path}: {e}")
        except Exception as e:
            logger.warning(f"Failed to resolve attachment name for {att.image_path}: {e}")
        attachment_names.append(resolved_name)
    return attachment_names, imported_object_names

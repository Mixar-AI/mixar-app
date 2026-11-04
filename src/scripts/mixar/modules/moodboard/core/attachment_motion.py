# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Best-effort presentation after the selection sync has committed attachments."""
import bpy
from mixar.config.logging_config import get_logger

_logger = get_logger(__name__)


def animate_attachments(scene, names):
    if bpy.app.background or bpy.context.scene != scene:
        return
    for index, name in enumerate(names):
        try:
            bpy.ops.mixie.moodboard_attachment_flight(
                image_name=name, delay=index * 0.055,
            )
        except (AttributeError, RuntimeError):
            # An older binary or a disappearing UI cannot block the attachment.
            _logger.debug("Attachment animation unavailable", exc_info=True)

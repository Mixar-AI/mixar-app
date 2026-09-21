# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Use the bundled bold face for notification headings and action labels."""

import os

import blf
import bpy

from mixar.config.logging_config import get_logger

from ..constants import EMPHASIS_FONT_FILE

_bold_font_id = None
_logger = get_logger(__name__)


def emphasis_font_id():
    """Load once; missing optional resources must never hide a notification."""
    global _bold_font_id
    if _bold_font_id is None:
        _bold_font_id = 0
        try:
            base = bpy.utils.system_resource('DATAFILES')
            path = os.path.join(base, 'fonts', EMPHASIS_FONT_FILE) if base else ''
            if path and os.path.isfile(path):
                font_id = blf.load(path)
                if font_id >= 0:
                    _bold_font_id = font_id
            else:
                _logger.debug('Notification bold font unavailable: %s', path)
        except Exception as exc:
            _logger.debug('Notification bold font could not load: %s', exc)
    return _bold_font_id


def text_measure(font_id, font_size):
    """Measure with the same face and size that the painter will use."""
    def measure(text):
        blf.size(font_id, font_size)
        return blf.dimensions(font_id, text)[0]
    return measure

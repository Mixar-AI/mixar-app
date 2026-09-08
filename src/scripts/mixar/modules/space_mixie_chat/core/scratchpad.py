# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded scene-session L2 namespaces; undo/load invalidate all live references."""

from collections import OrderedDict

import bpy

from ..constants import HARNESS_SCRATCHPAD_LIMIT

_PADS = OrderedDict()


def clear_scratchpads(*_args):
    _PADS.clear()


def scratchpad(key):
    for handlers in (bpy.app.handlers.undo_post, bpy.app.handlers.load_pre):
        if clear_scratchpads not in handlers:
            handlers.append(clear_scratchpads)
    if key not in _PADS:
        if len(_PADS) >= HARNESS_SCRATCHPAD_LIMIT:
            _PADS.popitem(last=False)
        _PADS[key] = {}
    _PADS.move_to_end(key)
    return _PADS[key]

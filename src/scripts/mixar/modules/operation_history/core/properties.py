# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-scene property holding the persistent operation-history id.

Persistent (NOT SKIP_SAVE): the id is saved in the .blend so a scene's operation log is
continuous when the file is reopened on the same machine. The log data itself lives in a
local directory keyed by this id (see core/store.py); only the small id travels in the file.
"""

import bpy
from bpy.props import StringProperty

from ..constants import SCENE_HISTORY_ID_PROP


def register():
    setattr(bpy.types.Scene, SCENE_HISTORY_ID_PROP, StringProperty(
        name="Mixar Operation History ID",
        description="Persistent per-scene id keying this scene's operation history.",
        default="",
    ))


def unregister():
    if hasattr(bpy.types.Scene, SCENE_HISTORY_ID_PROP):
        delattr(bpy.types.Scene, SCENE_HISTORY_ID_PROP)

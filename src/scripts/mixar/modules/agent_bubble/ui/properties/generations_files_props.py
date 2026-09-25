# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Media files found in the user's connected library folders.

Written ONLY by ``agent_bubble/core/library_media.py``; read by the C++
Library pane (``agent_ui_generations_data.cc``) by these exact names, so a
rename here must be matched there. Pinned by
``tests/test_library_folder_media.py``.

WindowManager + SKIP_SAVE: it is a cache of the disk, rebuilt every session,
and must never be serialised into a ``.blend``.
"""

import bpy
from bpy.props import CollectionProperty, IntProperty, StringProperty
from bpy.types import PropertyGroup

#: The WindowManager collection the pane reads.
FILES_PROP = "mixar_generations_files"

#: Field names the C++ reads from each row.
FIELD_NAMES = ("library", "path", "name", "kind", "mtime", "icon_id")


class MixarLibraryFileItem(PropertyGroup):
    """One image or video inside a connected library folder."""

    library: StringProperty(name="Library", options={'SKIP_SAVE'})
    path: StringProperty(name="Path", subtype='FILE_PATH', options={'SKIP_SAVE'})
    kind: StringProperty(name="Kind", description="IMAGE or VIDEO", options={'SKIP_SAVE'})
    mtime: IntProperty(name="Modified", options={'SKIP_SAVE'})
    icon_id: IntProperty(name="Preview Icon", options={'SKIP_SAVE'})


def register():
    bpy.utils.register_class(MixarLibraryFileItem)
    setattr(
        bpy.types.WindowManager,
        FILES_PROP,
        CollectionProperty(type=MixarLibraryFileItem, options={'SKIP_SAVE'}),
    )


def unregister():
    if hasattr(bpy.types.WindowManager, FILES_PROP):
        delattr(bpy.types.WindowManager, FILES_PROP)
    try:
        from mixar.modules.agent_bubble.core import library_media

        library_media.free()
    except Exception:  # noqa: BLE001 — never block unregister
        pass
    try:
        bpy.utils.unregister_class(MixarLibraryFileItem)
    except RuntimeError:
        pass

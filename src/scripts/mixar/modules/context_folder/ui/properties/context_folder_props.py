# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``Scene.mixie_context_folders``: the folders attached to this scene's chat.

Persisted with the file so a reopened project keeps its context, but each
row holds only the opaque id and a display name: the absolute root lives in
the machine-local registry (``core/registry.py``). The Agent island draws one
reference chip per row (``agent_bubble_reference_items.cc``).
"""

import bpy
from bpy.props import CollectionProperty, StringProperty
from bpy.types import PropertyGroup


class MixieContextFolder(PropertyGroup):
    folder_id: StringProperty(
        name="Folder ID",
        description="Opaque id resolved to a folder on this computer only",
        default="",
        maxlen=64,
        options={'HIDDEN'},
    )
    # ``name`` is PropertyGroup's built-in label: the folder's basename.


classes = (MixieContextFolder,)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass  # already registered (module reload)
    bpy.types.Scene.mixie_context_folders = CollectionProperty(
        type=MixieContextFolder,
        name="Context Folders",
        description="Folders the agent can read, view and import from while it works on this chat",
    )


def unregister():
    if hasattr(bpy.types.Scene, "mixie_context_folders"):
        del bpy.types.Scene.mixie_context_folders
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass

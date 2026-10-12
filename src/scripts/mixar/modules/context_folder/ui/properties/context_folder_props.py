# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``Scene.mixie_context_folders`` and ``Scene.mixie_context_files``: the
folders and single files attached to this scene's chat.

Persisted with the file so a reopened project keeps its context, but each
row holds only the opaque id and a display name: the absolute root or file
path lives in the machine-local registry (``core/registry.py``). The Agent
island draws one reference chip per row (``agent_bubble_reference_items.cc``).
``mixie_context_files_id`` is the synthetic folder id under which the files
reach the agent as one "Attached files" folder (``core/files.py``).
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


class MixieContextFile(PropertyGroup):
    file_id: StringProperty(
        name="File ID",
        description="Opaque id resolved to a file on this computer only",
        default="",
        maxlen=64,
        options={'HIDDEN'},
    )
    kind: StringProperty(
        name="Kind",
        description="File kind (video, document, text…) that picks the chip glyph",
        default="",
        options={'HIDDEN'},
    )
    origin: StringProperty(
        name="Origin",
        description="Which attach path made this chip (picker, blend, moodboard); only moodboard chips follow the board selection",
        default="",
        options={'HIDDEN'},
    )
    # ``name`` is the unique basename: the chip label and the agent's path.


classes = (MixieContextFolder, MixieContextFile)


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
    bpy.types.Scene.mixie_context_files = CollectionProperty(
        type=MixieContextFile,
        name="Context Files",
        description="Files the agent can read, view and import while it works on this chat",
    )
    bpy.types.Scene.mixie_context_files_id = StringProperty(
        name="Context Files ID",
        description="Opaque id of the folder the attached files form for the agent",
        default="",
        maxlen=64,
        options={'HIDDEN'},
    )


def unregister():
    for name in ("mixie_context_files_id", "mixie_context_files", "mixie_context_folders"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass

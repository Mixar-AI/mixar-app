# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Actions for the island's My Generations tab.

The pane itself is C++ and stateless — everything it can DO is one of the
operators below, bound to a painted button. Each one is deliberately thin and
delegates to a flow that already exists:

- Connecting a library calls Blender's OWN ``preferences.asset_library_add``
  rather than writing ``preferences.filepaths.asset_libraries`` here. That
  operator does the prefs write, sets the dirty flag, posts the notifier and
  clears the asset-list cache — four things a hand-rolled append would have to
  get right, and one of them (the cache clear) is why a hand-added library
  shows up empty until a restart. Like Blender, it does not force a
  ``save_userpref``: Preferences auto-save is what persists it, and forcing a
  write would also flush every unrelated preference the user is mid-edit on.
- Adding an asset to the scene is ``wm.append`` with the same
  ``<blend>/<ID type>/<name>`` addressing the asset browser uses. This is the
  BUTTON's path; dragging a tile into the viewport does not come through here
  at all — that is Blender's asset drag and the View3D's own asset dropbox.
- Selecting a still or a movie selects it ON THE MOODBOARD, which is the
  app-wide way an image becomes a reference (the chat composer mirrors the
  board selection, and Video Gen reads it directly). The image is already
  boarded — that is where the pane found it — so "add" would be a no-op and
  "select" is the honest verb.

No operator here writes anything the user did not ask for by clicking it.
"""

import logging
import os

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

logger = logging.getLogger(__name__)


def _registered_library_paths():
    """Absolute paths of every registered asset library, lower-cased."""
    try:
        libs = bpy.context.preferences.filepaths.asset_libraries
    except Exception:  # noqa: BLE001 — no preferences in a background run
        return {}
    out = {}
    for lib in libs:
        try:
            path = os.path.normcase(os.path.abspath(bpy.path.abspath(lib.path or "")))
        except Exception:  # noqa: BLE001 — a broken entry must not block the add
            continue
        if path:
            out[path] = lib.name
    return out


class MIXAR_OT_generations_add_library(Operator):
    """Connect a folder as an asset library, from inside the island."""

    bl_idname = "mixar.generations_add_library"
    bl_label = "Add Library"
    bl_description = (
        "Choose a folder to use as an asset library; its assets then appear "
        "in this tab and in Blender's Asset Browser"
    )
    bl_options = {'REGISTER'}

    directory: StringProperty(name="Library Folder", subtype='DIR_PATH')

    def invoke(self, context, _event):
        # A native folder picker, not a props dialog: a dialog opens behind
        # the always-on-top bubble window and looks like nothing happened
        # (the same finding the add-on project's New Add-on picker records).
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = (self.directory or "").strip()
        if not path:
            self.report({'ERROR'}, "No folder chosen")
            return {'CANCELLED'}
        path = os.path.abspath(bpy.path.abspath(path))
        if not os.path.isdir(path):
            self.report({'ERROR'}, "That folder does not exist")
            return {'CANCELLED'}

        existing = _registered_library_paths()
        already = existing.get(os.path.normcase(path))
        if already is not None:
            # Idempotent: re-picking a connected folder selects it rather than
            # registering a second entry pointing at the same place.
            context.window_manager.mixar_generations_library = already
            self.report({'INFO'}, f"Already connected as '{already}'")
            return {'FINISHED'}

        try:
            bpy.ops.preferences.asset_library_add(directory=path)
        except Exception as exc:  # noqa: BLE001 — surface, never swallow
            logger.exception("[Generations] Could not add asset library")
            self.report({'ERROR'}, f"Could not add the library: {exc}")
            return {'CANCELLED'}

        name = _registered_library_paths().get(os.path.normcase(path), "")
        if name:
            context.window_manager.mixar_generations_library = name
        self.report({'INFO'}, f"Connected '{name or os.path.basename(path)}'")
        return {'FINISHED'}


class MIXAR_OT_generations_add_asset(Operator):
    """Append the selected asset into the current scene."""

    bl_idname = "mixar.generations_add_asset"
    bl_label = "Add to Scene"
    bl_description = "Append this asset into the current scene"
    bl_options = {'REGISTER', 'UNDO'}

    blend_path: StringProperty(name="Blend File", default="")
    id_dir: StringProperty(name="ID Type", default="Object")
    asset_name: StringProperty(name="Asset Name", default="")

    def execute(self, _context):
        blend = (self.blend_path or "").strip()
        name = (self.asset_name or "").strip()
        id_dir = (self.id_dir or "Object").strip()
        if not blend or not name:
            self.report({'ERROR'}, "That asset has no file on disk")
            return {'CANCELLED'}
        if not os.path.isfile(blend):
            self.report({'ERROR'}, "The asset's .blend is missing")
            return {'CANCELLED'}

        # The asset browser addresses a datablock as
        # "<blend>/<ID type>/<name>"; `directory` must keep the trailing
        # separator or Blender reads the type folder as the file name.
        directory = os.path.join(blend, id_dir) + os.sep
        try:
            bpy.ops.wm.append(
                filepath=os.path.join(directory, name),
                directory=directory,
                filename=name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[Generations] Append failed")
            self.report({'ERROR'}, f"Could not add '{name}': {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Added '{name}' to the scene")
        return {'FINISHED'}


class MIXAR_OT_generations_select_media(Operator):
    """Select a generated still or movie on the scene's moodboard."""

    bl_idname = "mixar.generations_select_media"
    bl_label = "Select on Board"
    bl_description = (
        "Select this on the moodboard, which is how it becomes a reference "
        "for the generation tabs and the chat composer"
    )
    bl_options = {'REGISTER', 'UNDO'}

    image_name: StringProperty(name="Image", default="")

    def execute(self, context):
        scene = context.scene
        items = getattr(scene, "mixie_moodboard_images", None)
        if items is None:
            self.report({'ERROR'}, "This scene has no moodboard")
            return {'CANCELLED'}
        target = (self.image_name or "").strip()
        # Resolve BEFORE mutating. The selection is exclusive — it is the
        # reference set, and adding to whatever was already selected would
        # change what the next generation submits — so a miss used to clear
        # every item and then bail with CANCELLED, which pushes no undo step.
        # Clicking a stale tile (the asset list is a cache) wiped the user's
        # whole reference set unrecoverably.
        if not any(
            getattr(item, "image", None) is not None and item.image.name == target
            for item in items
        ):
            self.report({'ERROR'}, "That image is no longer on the board")
            return {'CANCELLED'}
        for item in items:
            image = getattr(item, "image", None)
            item.selected = image is not None and image.name == target
        self.report({'INFO'}, f"Selected '{target}' on the moodboard")
        return {'FINISHED'}


class MIXAR_OT_generations_select_splat(Operator):
    """Select a splat world's handle in the viewport."""

    bl_idname = "mixar.generations_select_splat"
    bl_label = "Select in Scene"
    bl_description = "Select this splat world's proxy handle in the viewport"
    bl_options = {'REGISTER', 'UNDO'}

    collection_name: StringProperty(name="Collection", default="")

    def execute(self, context):
        collection = bpy.data.collections.get((self.collection_name or "").strip())
        if collection is None:
            self.report({'ERROR'}, "That splat world is no longer in this file")
            return {'CANCELLED'}
        # The proxy Empty is a splat world's ONE handle — the point cloud and
        # the collider are hidden, and what the viewport shows is KIRI's GPU
        # pass, not geometry (moodboard/core/splat_lifecycle.py).
        proxy = None
        for obj in collection.all_objects:
            if obj.get("wl_role") == "proxy":
                proxy = obj
                break
        if proxy is None:
            self.report({'ERROR'}, "This splat world has no proxy handle")
            return {'CANCELLED'}
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except Exception:  # noqa: BLE001 — no object mode / no view layer
            pass
        proxy.select_set(True)
        context.view_layer.objects.active = proxy
        self.report({'INFO'}, f"Selected '{proxy.name}'")
        return {'FINISHED'}


class MIXAR_OT_generations_open_folder(Operator):
    """Reveal a generation's file in the system file browser."""

    bl_idname = "mixar.generations_open_folder"
    bl_label = "Open Folder"
    bl_description = "Show this file's folder in the system file browser"
    bl_options = {'REGISTER'}

    path: StringProperty(name="Path", default="")

    def execute(self, _context):
        path = bpy.path.abspath((self.path or "").strip())
        if not path:
            self.report({'ERROR'}, "This item has no file on disk")
            return {'CANCELLED'}
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if not os.path.isdir(folder):
            self.report({'ERROR'}, "That folder no longer exists")
            return {'CANCELLED'}
        try:
            bpy.ops.wm.path_open(filepath=folder)
        except Exception as exc:  # noqa: BLE001
            self.report({'ERROR'}, f"Could not open the folder: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    MIXAR_OT_generations_add_library,
    MIXAR_OT_generations_add_asset,
    MIXAR_OT_generations_select_media,
    MIXAR_OT_generations_select_splat,
    MIXAR_OT_generations_open_folder,
)

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Actions for the island's Library tab.

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
- Adding an asset to the scene goes through ``core/spawn_asset.py``. It
  loads the datablock with ``bpy.data.libraries.load`` and links it into a
  collection the viewport can see, then frames it. ``wm.append`` is not used:
  from this window it returns ``{'CANCELLED'}`` without raising and has no
  View3D to frame the result, so the button used to report success while the
  grid stayed empty. Dragging a tile does not come through here at all — that
  is Blender's asset drag and the View3D's own asset dropbox.
- Selecting a still or a movie selects it ON THE MOODBOARD, which is the
  app-wide way an image becomes a reference (the chat composer mirrors the
  board selection, and Video Gen reads it directly). The image is already
  boarded — that is where the pane found it — so "add" would be a no-op and
  "select" is the honest verb.

- A folder's images and videos (``core/library_media.py``) go onto the
  moodboard through the board's own ``load_media_file_to_board`` — the same
  loader the moodboard's Add Media uses — because a picture has no meaning as
  a 3D drop and the board is where every reference lives.
- Ctrl/Cmd/Shift-click builds a multi-selection
  (``mixar_generations_multi``); "Add N" then adds every selected folder
  file to the board and every selected 3D asset to the scene in one step.
- Removing a library only DISCONNECTS it (Blender's own
  ``preferences.asset_library_remove``); the folder and its files stay on
  disk, so it is undone by connecting the folder again.

No operator here writes anything the user did not ask for by clicking it.
"""

import logging
import os
import re

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

logger = logging.getLogger(__name__)

#: Must match ``asset_search/constants.py:GENERATION_LIBRARY_NAME``.
GENERATIONS_LIBRARY_NAME = "Mixar Generations"

#: ``<dir>/<file>.blend/<IDType>/<name>`` — an asset's library-relative
#: identifier, with either separator (Windows builds it with ``\\``).
_ASSET_RELID = re.compile(r"^(.*?\.blend)[\\/]([^\\/]+)[\\/](.+)$", re.I)


def _refresh_media(context, *, force=True):
    try:
        from mixar.modules.agent_bubble.core import library_media

        library_media.refresh(context, force=force)
    except Exception:  # noqa: BLE001 — the listing catches up on the next pump
        logger.debug("[Generations] media refresh failed", exc_info=True)


def selected_keys(wm) -> list:
    """Every selected tile key, active one last; empty when none."""
    multi = [k for k in (getattr(wm, "mixar_generations_multi", "") or "").split("\n") if k]
    active = getattr(wm, "mixar_generations_selected", "") or ""
    if not multi:
        return [active] if active else []
    if active in multi:
        multi.remove(active)
        multi.append(active)
    return multi


def toggle_selection(wm, key: str) -> None:
    """Add *key* to the selection, or take it out if it is already in."""
    keys = selected_keys(wm)
    if key in keys:
        keys.remove(key)
        active = keys[-1] if keys else ""
    else:
        keys.append(key)
        active = key
    wm.mixar_generations_multi = "\n".join(keys) if len(keys) > 1 else ""
    wm.mixar_generations_selected = active


def resolve_asset_key(key: str, libraries):
    """``(blend_path, id_dir, name)`` for an ``asset:<lib>:<relid>`` key.

    *libraries* maps a library name to its folder. None when the key is not an
    asset, names an unknown library, or does not parse.
    """
    if not key.startswith("asset:"):
        return None
    lib_name, sep, relid = key[len("asset:"):].partition(":")
    folder = libraries.get(lib_name) if sep else None
    match = _ASSET_RELID.match(relid) if folder else None
    if not match:
        return None
    return os.path.join(folder, match.group(1)), match.group(2), match.group(3)


def _library_folders():
    try:
        libs = bpy.context.preferences.filepaths.asset_libraries
    except Exception:  # noqa: BLE001 — no preferences in a background run
        return {}
    return {lib.name: bpy.path.abspath(lib.path or "") for lib in libs}


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
        _refresh_media(context)
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

    def execute(self, context):
        from mixar.modules.agent_bubble.core.spawn_asset import spawn_library_asset

        ok, message = spawn_library_asset(
            context, self.blend_path, self.id_dir, self.asset_name
        )
        self.report({'INFO'} if ok else {'ERROR'}, message)
        return {'FINISHED'} if ok else {'CANCELLED'}


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


class MIXAR_OT_generations_remove_library(Operator):
    """Disconnect a library folder from Mixar (its files stay on disk)."""

    bl_idname = "mixar.generations_remove_library"
    bl_label = "Remove Library"
    bl_description = (
        "Remove this folder from your libraries. Nothing is deleted from disk; "
        "add the folder again to bring it back"
    )
    bl_options = {'REGISTER'}

    library_name: StringProperty(name="Library", default="")

    def execute(self, context):
        name = (self.library_name or "").strip()
        if not name:
            self.report({'ERROR'}, "No library chosen")
            return {'CANCELLED'}
        if name == GENERATIONS_LIBRARY_NAME:
            # The auto-archive: removing it would only have it re-registered
            # on the next generation, and AI generations shows it anyway.
            self.report({'ERROR'}, "Mixar Generations is managed automatically")
            return {'CANCELLED'}
        try:
            libs = context.preferences.filepaths.asset_libraries
        except Exception:  # noqa: BLE001
            self.report({'ERROR'}, "Preferences are not available")
            return {'CANCELLED'}
        index = next((i for i, lib in enumerate(libs) if lib.name == name), -1)
        if index < 0:
            self.report({'ERROR'}, f"'{name}' is no longer connected")
            return {'CANCELLED'}
        try:
            bpy.ops.preferences.asset_library_remove(index=index)
        except Exception as exc:  # noqa: BLE001 — surface, never swallow
            logger.exception("[Generations] Could not remove asset library")
            self.report({'ERROR'}, f"Could not remove the library: {exc}")
            return {'CANCELLED'}
        wm = context.window_manager
        if getattr(wm, "mixar_generations_library", "") == name:
            wm.mixar_generations_library = ""
        wm.mixar_generations_selected = ""
        wm.mixar_generations_multi = ""
        _refresh_media(context)
        self.report({'INFO'}, f"Removed '{name}' (files were not deleted)")
        return {'FINISHED'}


class MIXAR_OT_generations_select(Operator):
    """Select a Library tile; Ctrl/Cmd/Shift-click selects several."""

    bl_idname = "mixar.generations_select"
    bl_label = "Select"
    bl_description = "Click to inspect; Ctrl/Cmd or Shift-click to select several"
    bl_options = {'INTERNAL'}

    # ``data_path`` is carried (never read) so the pane's shared button
    # identity and the QA provider recognise this as the selection button,
    # exactly as they did the stock ``wm.context_set_string`` it replaces.
    data_path: StringProperty(default="window_manager.mixar_generations_selected",
                              options={'HIDDEN', 'SKIP_SAVE'})
    value: StringProperty(name="Key", default="", options={'SKIP_SAVE'})
    extend: BoolProperty(name="Extend", default=False, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.extend = bool(event.ctrl or event.oskey or event.shift)
        return self.execute(context)

    def execute(self, context):
        wm = context.window_manager
        key = self.value or ""
        if self.extend and key:
            toggle_selection(wm, key)
        else:
            wm.mixar_generations_multi = ""
            wm.mixar_generations_selected = key
        return {'FINISHED'}


class MIXAR_OT_generations_clear_selection(Operator):
    """Deselect every Library tile."""

    bl_idname = "mixar.generations_clear_selection"
    bl_label = "Clear Selection"
    bl_description = "Deselect every tile"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        wm.mixar_generations_multi = ""
        wm.mixar_generations_selected = ""
        return {'FINISHED'}


class MIXAR_OT_generations_add_selected(Operator):
    """Add the selected folder media to the moodboard and assets to the scene."""

    bl_idname = "mixar.generations_add_selected"
    bl_label = "Add Selected"
    bl_description = (
        "Add the selected images and videos to the moodboard, and the selected "
        "3D assets to the scene"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from mixar.modules.agent_bubble.core.spawn_asset import spawn_library_asset
        from mixar.modules.moodboard.core.media_import import load_media_file_to_board

        keys = selected_keys(context.window_manager)
        if not keys:
            self.report({'WARNING'}, "Nothing is selected")
            return {'CANCELLED'}
        folders = _library_folders()
        boarded = spawned = 0
        failed = []
        for key in keys:
            if key.startswith("file:"):
                path = key[len("file:"):]
                ok = os.path.isfile(path) and load_media_file_to_board(context.scene, path)
                boarded += 1 if ok else 0
                if not ok:
                    failed.append(os.path.basename(path))
                continue
            asset = resolve_asset_key(key, folders)
            if asset is None:
                continue
            ok, _message = spawn_library_asset(context, *asset)
            spawned += 1 if ok else 0
            if not ok:
                failed.append(asset[2])
        parts = []
        if boarded:
            parts.append(f"{boarded} to the moodboard")
        if spawned:
            parts.append(f"{spawned} to the scene")
        if failed:
            shown = ", ".join(failed[:3]) + ("…" if len(failed) > 3 else "")
            parts.append(f"could not add {shown}")
        if not boarded and not spawned:
            self.report({'ERROR'}, "Nothing could be added" + (f": {shown}" if failed else ""))
            return {'CANCELLED'}
        self.report({'WARNING'} if failed else {'INFO'}, "Added " + "; ".join(parts))
        return {'FINISHED'}


classes = (
    MIXAR_OT_generations_add_library,
    MIXAR_OT_generations_remove_library,
    MIXAR_OT_generations_select,
    MIXAR_OT_generations_clear_selection,
    MIXAR_OT_generations_add_selected,
    MIXAR_OT_generations_add_asset,
    MIXAR_OT_generations_select_media,
    MIXAR_OT_generations_select_splat,
    MIXAR_OT_generations_open_folder,
)

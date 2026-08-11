# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat Export Operators (#26).

Provides the ``File → Export → Export .blend without chat history``
operator decided 2026-05-27. Strips every scene's
``mixie_chat_messages`` collection and writes a NEW .blend to the
user-picked path. The original file in memory is left untouched —
this is an "Export", not a destructive save.

Rationale: the per-scene chat persistence stores the agent
conversation INTO the .blend. When a user shares the file, their
full chat history travels with it (prompts, image refs, agent
responses). This operator gives an explicit affordance to make a
share-safe copy without destroying the working file's history.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

from mixar.config.logging_config import get_logger

from ...core.chat_serializer import (
    restore_propgroup as _restore_propgroup,
    snapshot_propgroup as _snapshot_propgroup,
)

logger = get_logger(__name__)


def _snapshot_chat(scenes) -> dict:
    """Capture each scene's chat-related collections recursively.

    Returns a dict ``{scene_name: list-of-message-dicts}``. Nested
    CollectionProperties (``attachments``, ``todo_items``,
    ``action_items``, ``image_items``) are walked recursively so
    nothing in the returned structure holds a Blender pointer that
    would be invalidated by the subsequent ``coll.clear()``.
    """
    snapshot = {}
    for scene in scenes:
        messages = list(getattr(scene, "mixie_chat_messages", []))
        snapshot[scene.name] = [_snapshot_propgroup(msg) for msg in messages]
    return snapshot


def _strip_chat(scenes) -> int:
    """Clear ``mixie_chat_messages`` on every scene; return total dropped."""
    dropped = 0
    for scene in scenes:
        coll = getattr(scene, "mixie_chat_messages", None)
        if coll is None:
            continue
        dropped += len(coll)
        coll.clear()
    return dropped


def _restore_chat(snapshot: dict) -> None:
    """Best-effort restore of the in-memory chat collections.

    Used after the export save so the WORKING file keeps its chat
    history INCLUDING nested attachments/todo_items/action_items/
    image_items. Recursive via ``_restore_propgroup``.
    """
    for scene in bpy.data.scenes:
        if scene.name not in snapshot:
            continue
        coll = getattr(scene, "mixie_chat_messages", None)
        if coll is None:
            continue
        coll.clear()
        for msg_data in snapshot[scene.name]:
            msg = coll.add()
            _restore_propgroup(msg, msg_data)


class MIXIE_CHAT_OT_export_without_chat(Operator, ExportHelper):
    """Export the current .blend without agent chat history.

    Writes a new .blend to the user-picked path with every scene's
    `mixie_chat_messages` cleared. The original file in memory is
    left intact — use this when you want to share the file without
    exposing the agent conversation.
    """

    bl_idname = "mixie_chat.export_without_chat"
    bl_label = "Export .blend without chat history"
    bl_options = {'REGISTER'}

    # ExportHelper conventions: filename_ext + filter_glob.
    filename_ext = ".blend"
    filter_glob: StringProperty(default="*.blend", options={'HIDDEN'})

    def execute(self, context):
        scenes = list(bpy.data.scenes)
        snapshot = _snapshot_chat(scenes)
        dropped = _strip_chat(scenes)
        try:
            bpy.ops.wm.save_as_mainfile(
                filepath=self.filepath,
                # copy=True: write to the new path WITHOUT changing
                # the current bpy.data.filepath. Keeps the working
                # file pointer intact so "save" in the open session
                # still targets the original.
                copy=True,
                compress=True,
            )
            self.report(
                {'INFO'},
                f"Exported chat-stripped copy ({dropped} message(s) "
                f"omitted from {len(scenes)} scene(s)).",
            )
            logger.info(
                f"[EXPORT_WITHOUT_CHAT] wrote {self.filepath} — dropped "
                f"{dropped} message(s) across {len(scenes)} scene(s)"
            )
        except Exception as e:
            logger.error(f"[EXPORT_WITHOUT_CHAT] save_as_mainfile failed: {e}")
            self.report({'ERROR'}, f"Export failed: {e}")
            return {'CANCELLED'}
        finally:
            # Always restore the in-memory chat, even on failure.
            # Stripping was destructive on the in-RAM scene; without
            # restore the user would lose chat history in their
            # working session.
            _restore_chat(snapshot)

        return {'FINISHED'}


def _menu_func_export(self, context):
    """Adds the operator to File → Export.

    Blender invokes this for every registered draw-callback under
    the export menu. The icon + label match the conventional shape
    of other in-tree exporters.
    """
    self.layout.operator(
        MIXIE_CHAT_OT_export_without_chat.bl_idname,
        text="Mixar Chat: Export .blend without chat history",
        icon='EXPORT',
    )


classes = (
    MIXIE_CHAT_OT_export_without_chat,
)

# Module-level flag for menu-append idempotency. Blender doesn't have a
# public API to query "is this draw_func already appended", so the
# addon convention is to track it ourselves. Without this guard a
# reload (script disable + re-enable) would add the menu entry twice.
_menu_registered = False


def register():
    global _menu_registered
    for cls in classes:
        bpy.utils.register_class(cls)
    if not _menu_registered:
        bpy.types.TOPBAR_MT_file_export.append(_menu_func_export)
        _menu_registered = True


def unregister():
    global _menu_registered
    if _menu_registered:
        try:
            bpy.types.TOPBAR_MT_file_export.remove(_menu_func_export)
        except Exception:
            pass
        _menu_registered = False
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

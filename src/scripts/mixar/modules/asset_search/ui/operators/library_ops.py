# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators for the 'Libraries to Train' enrollment list.

Refresh rebuilds the WindowManager list from the registered asset libraries
(merging the persisted enrollment) and counts each library's asset-marked
datablocks. Counting opens every .blend metadata-only, so it runs on the
user's explicit Refresh, never on panel redraw.
"""

from pathlib import Path

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.core import library_enrollment as enroll

logger = get_logger(__name__)


def _count_assets(library_path: Path) -> int:
    """Count asset-marked objects + collections across a library's .blends."""
    total = 0
    for blend_file in library_path.glob("**/*.blend"):
        try:
            with bpy.data.libraries.load(
                str(blend_file), assets_only=True
            ) as (data_from, _):
                total += len(data_from.objects) + len(data_from.collections)
        except Exception:
            continue
    return total


_names_synced = False


def ensure_library_list_synced(context):
    """Once per session, populate the list with names (no scan) off the draw
    thread — so the panel shows libraries without a manual Refresh."""
    global _names_synced
    if _names_synced:
        return
    _names_synced = True

    def _do():
        try:
            rebuild_library_list(bpy.context, count=False)
        except Exception:
            logger.opt(exception=True).debug("[Enrollment] name sync failed")
        return None  # one-shot

    try:
        bpy.app.timers.register(_do, first_interval=0.0)
    except Exception:
        pass


def rebuild_library_list(context, count=True):
    """Sync WM.mixie_asset_libraries with the registered libraries + enrollment."""
    wm = context.window_manager
    coll = wm.mixie_asset_libraries
    enrolled = enroll.enrolled_names()

    enroll._SYNCING = True  # setting .enabled must not rewrite the config
    try:
        coll.clear()
        for lib in context.preferences.filepaths.asset_libraries:
            item = coll.add()
            item.name = lib.name
            item.path = lib.path
            item.enabled = lib.name in enrolled
            if count:
                p = Path(lib.path)
                item.asset_count = _count_assets(p) if p.is_dir() else 0
            else:
                item.asset_count = -1
    finally:
        enroll._SYNCING = False

    for area in context.screen.areas:
        if area.type == 'FILE_BROWSER':
            area.tag_redraw()


class MIXIE_OT_refresh_libraries(Operator):
    """Rescan asset libraries and count their assets"""

    bl_idname = "mixie.refresh_libraries"
    bl_label = "Refresh Libraries"
    bl_description = (
        "Rescan the registered asset libraries and count the assets in each "
        "(reads every .blend once — may take a moment for large libraries)"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        enroll.invalidate_cache()
        rebuild_library_list(context, count=True)
        n = len(context.window_manager.mixie_asset_libraries)
        self.report({"INFO"}, f"Scanned {n} asset librar" + ("y" if n == 1 else "ies"))
        return {"FINISHED"}


class MIXIE_OT_set_all_libraries(Operator):
    """Enable or disable every library for training at once"""

    bl_idname = "mixie.set_all_libraries"
    bl_label = "Set All Libraries"
    bl_options = {"REGISTER", "INTERNAL"}

    enable: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        coll = context.window_manager.mixie_asset_libraries
        if not coll:
            rebuild_library_list(context, count=False)
            coll = context.window_manager.mixie_asset_libraries
        names = {item.name for item in coll}
        enroll._write(names if self.enable else set())
        enroll.invalidate_cache()
        enroll._SYNCING = True
        try:
            for item in coll:
                item.enabled = self.enable
        finally:
            enroll._SYNCING = False
        for area in context.screen.areas:
            if area.type == 'FILE_BROWSER':
                area.tag_redraw()
        return {"FINISHED"}


classes = (
    MIXIE_OT_refresh_libraries,
    MIXIE_OT_set_all_libraries,
)

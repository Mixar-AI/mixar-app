# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Splat worlds in the outliner: tag at import, tidy after delete, upgrade old files.

A splat is Blender's built-in Gaussian splat object (``splat_native``), so
hide, select, render and delete are ordinary object operations. Two things
still need Mixar:

* deleting a world's splat leaves its hidden collider behind (it is only
  there for placement ray-casts). A depsgraph handler schedules one debounced
  check per burst of edits; when a world this codebase imported has no splat
  left, its stamped leftovers are removed;
* files saved with the retired KIRI addon are converted to built-in splats
  when they open (``splat_legacy``).

Neither full-scene scans nor scene edits run inside ``depsgraph_update_post``.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.moodboard.core.splat_native import is_splat

logger = get_logger(__name__)

# Collections created by our two splat importers, and only those, may be
# purged when their world is deleted.
SPLAT_WORLD_FLAG = "mixar_splat_world"

# Roles stamped at import; anything else in the collection is the user's.
_PURGEABLE_ROLES = {"splat", "collider"}

_CHECK_DELAY_S = 0.2

_known_splats = None   # frozenset[str] | None
_check_pending = False


def finalize_splat_handles(collection, splat_objs: list) -> None:
    """Stamp an imported world so its leftovers can be tidied after a delete.

    Shared by both importers (generated World Labs worlds and local
    ``.spz``/``.ply`` files), so the outliner contract has one definition. The
    purge flag is set only when the import produced a splat: a world without
    one has nothing to lose, and flagging it would read as already deleted.
    """
    splats = [obj for obj in splat_objs if is_splat(obj)]
    for obj in splats:
        try:
            obj["wl_role"] = "splat"
        except Exception:  # noqa: BLE001 - freed datablock
            pass
    if splats:
        try:
            collection[SPLAT_WORLD_FLAG] = True
        except Exception:  # noqa: BLE001 - collection freed
            pass


def _splat_names() -> frozenset:
    return frozenset(obj.name for obj in bpy.data.objects
                     if obj.get("wl_role") == "splat" and is_splat(obj))


def _purge_orphaned_worlds(splats: frozenset) -> int:
    """Remove import-created leftovers of worlds whose splat the user deleted.

    Scoped hard: only collections this codebase created (``mixar_splat_world``)
    and only objects it stamped with ``wl_role``; anything the user parked in
    there is left alone, and a collection that still holds such objects
    survives.
    """
    removed = 0
    for collection in list(bpy.data.collections):
        if not collection.get(SPLAT_WORLD_FLAG):
            continue
        if any(obj.name in splats for obj in collection.objects):
            continue  # world still alive
        for obj in list(collection.objects):
            if str(obj.get("wl_role", "") or "") in _PURGEABLE_ROLES:
                bpy.data.objects.remove(obj, do_unlink=True)
                removed += 1
        if not collection.objects and not collection.children:
            bpy.data.collections.remove(collection)
    return removed


def note_splats_imported() -> None:
    """Adopt the current splat set as the baseline (called after an import)."""
    global _known_splats

    _known_splats = _splat_names()


@persistent
def on_depsgraph_update(_scene=None, _depsgraph=None):
    """Coalesce updates; operator loops must not scan every object per edit."""
    global _check_pending

    if _check_pending:
        return
    _check_pending = True
    try:
        bpy.app.timers.register(_check_splats, first_interval=_CHECK_DELAY_S)
    except Exception:  # noqa: BLE001 - restricted context
        _check_pending = False


def _check_splats():
    """Detect a deleted splat once after a burst of edits, on the main loop."""
    global _known_splats, _check_pending

    _check_pending = False
    try:
        splats = _splat_names()
        if _known_splats is not None and not splats >= _known_splats:
            removed = _purge_orphaned_worlds(splats)
            if removed:
                logger.info("[SplatLifecycle] removed %d leftover(s) of deleted "
                            "splat world(s)", removed)
        _known_splats = splats
    except Exception:  # noqa: BLE001 - never let a timer die on scene edits
        logger.debug("[SplatLifecycle] check failed", exc_info=True)
    return None


def _convert_legacy():
    """Timer: upgrade a freshly opened file's KIRI splats, then re-baseline."""
    global _known_splats

    try:
        from mixar.modules.moodboard.core.splat_legacy import convert_kiri_splats

        converted = convert_kiri_splats()
        for obj in converted:
            for collection in obj.users_collection:
                if collection.name.startswith(("WorldLabs_", "Splat_")):
                    collection[SPLAT_WORLD_FLAG] = True
    except Exception:  # noqa: BLE001 - never block opening a file
        logger.warning("[SplatLifecycle] KIRI splat conversion failed", exc_info=True)
    _known_splats = _splat_names()
    return None


@persistent
def on_load_post(_filepath=None):
    """Re-baseline for the newly opened file and upgrade any KIRI splats."""
    global _known_splats

    cancel_pending()
    _known_splats = None
    try:
        bpy.app.timers.register(_convert_legacy, first_interval=0.0)
    except Exception:  # noqa: BLE001 - restricted context
        pass


def cancel_pending() -> None:
    global _check_pending

    _check_pending = False
    try:
        for callback in (_check_splats, _convert_legacy):
            if bpy.app.timers.is_registered(callback):
                bpy.app.timers.unregister(callback)
    except Exception:  # noqa: BLE001 - interpreter shutdown
        pass

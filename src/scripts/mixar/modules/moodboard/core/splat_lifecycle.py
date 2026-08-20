# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Keep KIRI's process-global splat runtime in step with the outliner.

KIRI draws splats from a process-global cache + GPU textures rebuilt only by
its own operators, so ordinary outliner edits desynchronise it:

* deleting a proxy sets ``bpy.gaussian_global_needs_update``, after which the
  draw handler bails out for **every** splat ("Global textures missing - run
  script_3 first") until someone presses KIRI's Update Scene;
* the cache holds its own copy of the gaussian blob keyed on the proxy name,
  so deleting only the source point-cloud mesh changes nothing on screen;
* a world whose proxy is gone leaves its hidden source mesh behind, and that
  mesh still renders splat quads through ``KIRI_3DGS_Render_GN`` at F12.

This module owns the reconciliation: a depsgraph handler *detects* proxy
add/remove and visibility changes, a debounced timer *does the work* (never
mutate scene data inside ``depsgraph_update_post``).

Hiding itself is handled inside the vendored addon — see the MIXAR PATCH in
``kiri_3dgs_render/__init__.py`` (``mixar_object_visibility``), which finally
feeds the visibility slot ``assets/vert.glsl`` has always honoured.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.moodboard.core import splat_render_camera as src

logger = get_logger(__name__)

# Collections created by our two splat importers, and only those, may be
# purged when their world is deleted.
SPLAT_WORLD_FLAG = "mixar_splat_world"

# Roles stamped at import; anything else in the collection is the user's.
_PURGEABLE_ROLES = {"splat", "collider", "proxy"}

_RECONCILE_DELAY_S = 0.2

_known_proxies = None      # frozenset[str] | None
_known_visibility = None   # tuple[bool, ...] | None
_reconcile_pending = False


# --------------------------------------------------------------------------- #
# Import-time finalize
# --------------------------------------------------------------------------- #

def finalize_splat_handles(collection, splat_objs: list, proxy_objs: list) -> None:
    """Make an imported world selectable in the viewport, deletable in the outliner.

    What the user sees is drawn by KIRI's GPU handler, not by geometry, so the
    only clickable part of a splat world is its proxy Empty — which KIRI
    creates at ``empty_display_size = 0.1``, invisible inside a room-scale
    world. Scale it to the world, draw it in front, and stamp the roles the
    reconciler above needs: the collection flag marks the world as ours to
    purge, ``wl_role`` marks which objects belong to it.

    Shared by both importers (generated World Labs worlds and local
    ``.spz``/``.ply`` files), so the outliner contract has one definition.

    The purge flag is set ONLY when a proxy was actually built: KIRI's proxy
    step degrades gracefully (``_enable_splat_render`` returns nothing and the
    world stays a visible point cloud), and such a world has no proxy to lose,
    so flagging it would make the next reconcile read it as already-deleted and
    purge a perfectly good import.
    """
    if proxy_objs:
        try:
            collection[SPLAT_WORLD_FLAG] = True
        except Exception:  # noqa: BLE001 - collection freed
            pass

    for obj in splat_objs:  # already set on the World Labs path; the local one needs it
        try:
            obj["wl_role"] = "splat"
        except Exception:  # noqa: BLE001
            pass

    size = _proxy_display_size(splat_objs)
    for proxy in proxy_objs:
        try:
            proxy["wl_role"] = "proxy"
            if proxy.type == "EMPTY":
                proxy.empty_display_size = size
                proxy.show_in_front = True
                proxy.show_name = True
        except Exception:  # noqa: BLE001
            continue


def _proxy_display_size(splat_objs: list) -> float:
    """~4% of the world's footprint — big enough to click, small enough not to
    clutter the room the user is directing inside."""
    try:
        footprint = max(
            max(obj.dimensions.x, obj.dimensions.y) for obj in splat_objs
        )
        return max(0.25, 0.04 * float(footprint))
    except Exception:  # noqa: BLE001 - no evaluated dimensions yet
        return 0.25


# --------------------------------------------------------------------------- #
# State snapshots
# --------------------------------------------------------------------------- #

def _proxy_names() -> frozenset:
    return frozenset(obj.name for obj in src._saved_splat_proxies())


def _visibility_snapshot() -> tuple:
    """(name, visible) per proxy — hide/unhide never changes a transform."""
    snapshot = []
    for proxy in src._saved_splat_proxies():
        snapshot.append((proxy.name, _is_visible(proxy)))
    return tuple(sorted(snapshot))


def _is_visible(obj) -> bool:
    try:
        if obj.hide_viewport:
            return False
        return bool(obj.visible_get())
    except (ReferenceError, RuntimeError):
        # Freed datablock, or not in the active view layer (excluded).
        return False


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #

def _prune_stale_cache(proxies: frozenset) -> bool:
    """Drop cache entries whose proxy is gone. Returns True if the cache is stale.

    KIRI's own pruning lives in a closure inside its draw handler, and the
    rebuild below would raise on the first freed ``Object`` reference, so we
    prune before calling it.
    """
    cache = getattr(bpy, "gaussian_object_cache", None)
    if not isinstance(cache, dict):
        return False
    for name in [n for n in cache if n not in proxies]:
        del cache[name]
    # A proxy that is not cached at all (undo re-added it, or the file was
    # appended into) cannot be rebuilt from the cache — force reconstruction
    # from the proxies' saved gaussian_data instead.
    return any(name not in cache for name in proxies)


def _sync_render_visibility(proxies: list) -> None:
    """Mirror each proxy's viewport visibility onto its source mesh's render flag.

    The proxy is the world's single handle: it is what the user sees and the
    only object they can click. Its source mesh is permanently eye-hidden
    behind it, but ``hide_set`` is viewport-only — without this, a world hidden
    in the viewport still renders its splat quads at F12.
    """
    wanted = {}
    for proxy in proxies:
        uuid = str(proxy.get("source_mesh_uuid", "") or "")
        if uuid:
            wanted[uuid] = _is_visible(proxy)
    if not wanted:
        return
    for obj in bpy.data.objects:
        visible = wanted.get(str(obj.get("gaussian_source_uuid", "") or ""))
        if visible is None:
            continue
        if obj.hide_render != (not visible):
            obj.hide_render = not visible


def _purge_orphaned_worlds(proxies: frozenset) -> int:
    """Remove import-created splat collections whose proxy the user deleted.

    Deleting the proxy IS deleting the world, so the leftovers — the hidden
    point-cloud mesh (which still renders through its geometry nodes) and the
    collider — must go with it. Scoped hard: only collections this codebase
    created (``mixar_splat_world``) and only objects it stamped with
    ``wl_role``; anything the user parked in there is left alone, and a
    collection that still holds such objects survives.
    """
    removed = 0
    for collection in list(bpy.data.collections):
        if not collection.get(SPLAT_WORLD_FLAG):
            continue
        if any(obj.name in proxies for obj in collection.objects):
            continue  # world still alive
        for obj in list(collection.objects):
            if str(obj.get("wl_role", "") or "") in _PURGEABLE_ROLES:
                bpy.data.objects.remove(obj, do_unlink=True)
                removed += 1
        if not collection.objects and not collection.children:
            bpy.data.collections.remove(collection)
    return removed


def _rebuild_kiri_runtime(proxies: frozenset, force_reconstruct: bool) -> None:
    """Rebuild the global gaussian textures, or tear the runtime down."""
    kiri = src._ready_kiri_module()
    if kiri is None:
        return
    if not proxies:
        # Nothing left to draw: clear the cache, textures and draw handler so
        # the viewport stops paying for them.
        getattr(kiri, src._KIRI_CLEANUP_FN)(False)
        logger.info("[SplatLifecycle] last splat removed; KIRI runtime cleared")
        return
    if force_reconstruct and hasattr(bpy, "gaussian_object_cache"):
        delattr(bpy, "gaussian_object_cache")
    getattr(kiri, src._KIRI_TEXTURE_FN)()
    logger.info("[SplatLifecycle] rebuilt KIRI textures for %d splat(s)", len(proxies))


def reconcile_splats():
    """Timer callback: bring KIRI's runtime and the scene back into agreement."""
    global _known_proxies, _known_visibility, _reconcile_pending

    _reconcile_pending = False
    try:
        proxies = _proxy_names()
        if proxies != _known_proxies:
            force = _prune_stale_cache(proxies)
            _purge_orphaned_worlds(proxies)
            _rebuild_kiri_runtime(proxies, force)
            _known_proxies = proxies
        _sync_render_visibility(src._saved_splat_proxies())
        _known_visibility = _visibility_snapshot()
    except Exception:  # noqa: BLE001 - never let a timer die on scene edits
        logger.debug("[SplatLifecycle] reconcile failed", exc_info=True)
    return None


def request_reconcile() -> None:
    """Debounce a reconcile onto a timer (scene edits are unsafe in handlers)."""
    global _reconcile_pending

    if _reconcile_pending:
        return
    _reconcile_pending = True
    try:
        bpy.app.timers.register(reconcile_splats, first_interval=_RECONCILE_DELAY_S)
    except Exception:  # noqa: BLE001 - restricted context
        _reconcile_pending = False


def note_splats_imported() -> None:
    """Adopt the current splat set as the baseline (called after an import)."""
    global _known_proxies, _known_visibility

    _known_proxies = _proxy_names()
    _known_visibility = _visibility_snapshot()


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #

@persistent
def on_depsgraph_update(_scene=None, _depsgraph=None):
    """Detect only; all mutation happens in the debounced timer."""
    global _known_proxies, _known_visibility

    if _reconcile_pending:
        return
    try:
        proxies = _proxy_names()
    except Exception:  # noqa: BLE001 - bpy.data restricted
        return
    if _known_proxies is None:
        _known_proxies = proxies
        _known_visibility = _visibility_snapshot()
        return
    if proxies != _known_proxies:
        request_reconcile()
        return
    if not proxies:
        return
    if _visibility_snapshot() != _known_visibility:
        request_reconcile()


@persistent
def on_load_post(_filepath=None):
    """Re-baseline for the newly opened file (its splats are not 'new')."""
    global _known_proxies, _known_visibility, _reconcile_pending

    _reconcile_pending = False
    _known_proxies = None
    _known_visibility = None


def cancel_pending() -> None:
    global _reconcile_pending

    _reconcile_pending = False
    try:
        if bpy.app.timers.is_registered(reconcile_splats):
            bpy.app.timers.unregister(reconcile_splats)
    except Exception:  # noqa: BLE001 - interpreter shutdown
        pass

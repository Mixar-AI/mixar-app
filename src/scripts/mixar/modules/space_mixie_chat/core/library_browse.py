"""Library chat mode — browse, search, and place library assets from chat.

Switch Mixie to LIBRARY mode and the chat shows a grid of clickable asset
thumbnails (every enrolled-library asset, or a filtered subset as you type in the
composer); clicking one appends that asset into the scene at the 3D cursor — no
asset-browser space needed.

Reuses infrastructure already built for the agent asset-picker: thumbnails come
from ``asset_choice_previews`` (append → embedded preview or EEVEE render →
bpy.data.images), rendered on the same C++ action-button path. Search is a local,
instant, credit-free substring filter (semantic search stays in AGENT mode). The
asset list is the same enrolled-library scan the trainer uses.
"""

import uuid
from pathlib import Path

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Thumbnails shown at once. The chat renders action buttons as a vertical list
# of thumbnail-left + label rows, so this is capped low to keep the bubble
# legible; typing narrows the set. (A compact multi-column grid would need a
# C++ layout change — tracked as a follow-up.)
_MAX_GRID = 12
LIBRARY_BUBBLE_PREFIX = "libbrowse:"
LIB_ADD_PREFIX = "lib_add:"

# Enrolled-library asset index: [{name, library, blend_file, type}]. Cached
# because the scan opens every .blend on the main thread; rebuilt on mode entry
# and whenever invalidate() is called (e.g. after a train).
_asset_cache = None


def invalidate() -> None:
    global _asset_cache
    _asset_cache = None


def _enumerate_assets(context, force=False):
    """Scan ENROLLED libraries for marked assets (name/library/blend_file/type).

    Type-aware: a collection asset whose .blend also holds a same-named member
    object is listed once, as the Collection (which carries the preview and is
    what the user means)."""
    global _asset_cache
    if _asset_cache is not None and not force:
        return _asset_cache

    from mixar.modules.asset_search.core.library_enrollment import (
        enrolled_libraries,
    )

    assets = []
    seen = set()
    for lib in enrolled_libraries(context):
        root = Path(bpy.path.abspath(lib.path or ""))
        if not root.is_dir():
            continue
        for blend in root.glob("**/*.blend"):
            rel = str(blend.relative_to(root)).replace("\\", "/")
            try:
                with bpy.data.libraries.load(str(blend), assets_only=True) as (
                    data_from, _to,
                ):
                    colls = set(getattr(data_from, "collections", []))
                    objs = set(data_from.objects)
            except Exception:
                continue
            for name in colls:
                key = (lib.name, rel, name)
                if key in seen:
                    continue
                seen.add(key)
                assets.append({"name": name, "library": lib.name,
                               "blend_file": rel, "type": "Collection"})
            for name in objs:
                if name in colls:  # collection member shares the name — collection wins
                    continue
                key = (lib.name, rel, name)
                if key in seen:
                    continue
                seen.add(key)
                assets.append({"name": name, "library": lib.name,
                               "blend_file": rel, "type": "Object"})

    assets.sort(key=lambda a: a["name"].lower())
    _asset_cache = assets
    return assets


def _matches(asset, query: str) -> bool:
    if not query:
        return True
    hay = f"{asset['name']} {asset['type']} {asset['library']}".lower()
    return all(tok in hay for tok in query.lower().split())


def _redraw():
    try:
        from .ui_utils import redraw_chat_areas
        redraw_chat_areas()
    except Exception:
        for window in getattr(bpy.context.window_manager, "windows", []):
            for area in window.screen.areas:
                area.tag_redraw()


def _remove_grid_bubbles(scene) -> None:
    """Drop any prior library-browse bubble so the grid refreshes in place."""
    for i in range(len(scene.mixie_chat_messages) - 1, -1, -1):
        bid = getattr(scene.mixie_chat_messages[i], "bubble_id", "") or ""
        if bid.startswith(LIBRARY_BUBBLE_PREFIX):
            scene.mixie_chat_messages.remove(i)


def _post_bubble(scene, content: str):
    msg = scene.mixie_chat_messages.add()
    msg.bubble_id = f"{LIBRARY_BUBBLE_PREFIX}{uuid.uuid4().hex[:8]}"
    msg.sender = "AGENT"
    msg.message_type = "AGENT"
    msg.content = content
    msg.text = content
    try:
        from .markdown_parser import parse_markdown_to_segments
        from .message_helpers import set_markdown_segments
        set_markdown_segments(
            msg, parse_markdown_to_segments(content, streaming=False)
        )
    except Exception:
        pass
    return msg


def build_library_grid(context, query: str = "", force: bool = False) -> None:
    """(Re)build the in-chat asset grid for *query* ("" = show everything)."""
    scene = context.scene
    if not hasattr(scene, "mixie_chat_messages"):
        return
    query = (query or "").strip()

    assets = _enumerate_assets(context, force=force)
    _remove_grid_bubbles(scene)

    if not assets:
        _post_bubble(
            scene,
            "**Your library is empty.** Enroll an asset library in the Assets "
            "workspace — it trains automatically, then its assets show up here.",
        )
        _redraw()
        return

    filtered = [a for a in assets if _matches(a, query)]
    shown = filtered[:_MAX_GRID]

    if query:
        header = f"**{len(filtered)}** asset(s) matching “{query}”"
    else:
        header = f"**Your library** — {len(assets)} asset(s)"
    if len(filtered) > len(shown):
        header += f" · showing the first {len(shown)}, refine your search"
    if not shown:
        header += "\n\nNo matches — try a different search."
        _post_bubble(scene, header)
        _redraw()
        return
    header += "\n\nClick an asset to add it to the scene at the 3D cursor."

    msg = _post_bubble(scene, header)
    msg.action_items.clear()
    for i, asset in enumerate(shown):
        action = msg.action_items.add()
        action.label = asset["name"]
        action.value = f"{LIB_ADD_PREFIX}{i}"
        action.style = "DEFAULT"
        action.asset_name = asset["name"]
        action.library = asset["library"]
        action.blend_file = asset["blend_file"]
        action.asset_type = asset["type"]

    # Generate/attach thumbnails via the asset-picker pipeline (one per tick).
    try:
        from . import asset_choice_previews
        asset_choice_previews.schedule(scene, msg)
    except Exception:
        logger.exception("[LibraryMode] preview scheduling failed")

    scene.mixie_chat_user_has_engaged = True
    _redraw()


def execute_library_mode(operator, context):
    """Composer send in LIBRARY mode: the typed text is a search over the
    library ("" shows everything). Called from chat_ops.execute."""
    scene = context.scene
    query = (getattr(scene, "mixie_chat_input", "") or "").strip()
    build_library_grid(context, query, force=False)
    try:
        scene.mixie_chat_input = ""  # clear the composer
    except Exception:
        pass
    return {'FINISHED'}


def schedule_show_all() -> None:
    """Show the full grid on the next tick — used when the user switches INTO
    LIBRARY mode (the enum update callback can't safely scan .blends itself)."""
    def _show():
        ctx = bpy.context
        if getattr(getattr(ctx, "scene", None), "mixie_chat_mode", "") == 'LIBRARY':
            try:
                build_library_grid(ctx, "", force=True)
            except Exception:
                logger.exception("[LibraryMode] show-all failed")
        return None

    try:
        bpy.app.timers.register(_show, first_interval=0.1)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Add to scene
# --------------------------------------------------------------------------- #

_MEASURABLE = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def add_asset_to_scene(context, library, blend_file, asset_name, asset_type):
    """Append the asset (object OR collection) at the 3D cursor. Returns
    (ok, message)."""
    import mathutils

    from .asset_choice_previews import _resolve_blend_path

    blend_path = _resolve_blend_path({"library": library, "blend_file": blend_file})
    if not blend_path or not Path(blend_path).exists():
        invalidate()
        return False, "That asset's file could not be found."

    prefer_collection = (asset_type or "").lower().startswith("collection")
    try:
        with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
            in_objects = asset_name in data_from.objects
            in_collections = asset_name in getattr(data_from, "collections", [])
            is_collection = in_collections and (prefer_collection or not in_objects)
            if is_collection:
                data_to.collections = [asset_name]
            elif in_objects:
                data_to.objects = [asset_name]
            else:
                return False, f"'{asset_name}' is not in the asset file anymore."

        if is_collection:
            coll = data_to.collections[0]
            if coll is None:
                return False, "The asset appended empty."
            context.scene.collection.children.link(coll)
            members = list(coll.all_objects)
        else:
            members = [o for o in data_to.objects if o is not None]
            target = context.collection or context.scene.collection
            for o in members:
                if o.name not in target.objects:
                    try:
                        target.objects.link(o)
                    except RuntimeError:
                        pass
        if not members:
            return False, "The asset appended empty."

        context.view_layer.update()

        # Move so the aggregate footprint's bottom-centre sits at the 3D cursor.
        member_set = set(members)
        roots = [o for o in members if o.parent is None or o.parent not in member_set]
        pts = []
        for o in members:
            if o.type in _MEASURABLE and len(o.bound_box):
                pts.extend(o.matrix_world @ mathutils.Vector(c) for c in o.bound_box)
        cursor = context.scene.cursor.location
        if pts:
            xs = [p.x for p in pts]
            ys = [p.y for p in pts]
            zs = [p.z for p in pts]
            offset = mathutils.Vector((
                cursor.x - (min(xs) + max(xs)) / 2.0,
                cursor.y - (min(ys) + max(ys)) / 2.0,
                cursor.z - min(zs),
            ))
        else:
            offset = mathutils.Vector((0.0, 0.0, 0.0))
        for o in roots:
            o.location = o.location + offset
        context.view_layer.update()

        for o in list(context.selected_objects):
            o.select_set(False)
        for o in members:
            try:
                o.select_set(True)
            except Exception:
                pass
        if roots:
            context.view_layer.objects.active = roots[0]
        return True, asset_name
    except Exception:
        logger.exception("[LibraryMode] add-to-scene failed for %s", asset_name)
        return False, "Could not add the asset to the scene."

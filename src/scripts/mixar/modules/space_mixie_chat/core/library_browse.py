# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Library chat mode — browse, search, and place library assets from chat.

Switch Mixie to LIBRARY mode and the chat shows a grid of clickable asset
thumbnails (every enrolled-library asset, or a filtered subset as you type in the
composer); clicking one appends that asset into the scene at the 3D cursor — no
asset-browser space needed.

Reuses infrastructure already built for the agent asset-picker: thumbnails come
from ``asset_choice_previews`` (append → embedded preview or EEVEE render →
bpy.data.images), rendered on the same C++ action-button path.

Search parity: a typed query runs the SAME backend semantic search as the asset
browser panel (``/api/v1/asset-search/search`` over the trained embeddings), so
the two search boxes return the same assets — "globe" finds a globe-shaped asset
whose NAME is a UUID. An empty send still browses everything locally, and the
local name filter remains only as the offline fallback (with a note).
"""

import threading
import uuid
from pathlib import Path

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Thumbnails shown at once. HARD-CAPPED by the C++ slot reader, which copies at
# most SLOT_MAX_ACTION_ITEMS (10) action items and SILENTLY TRUNCATES past it —
# so stay under 10 or assets vanish with no indicator. The chat also renders
# action buttons as a vertical list of thumbnail-left + label rows, so a low cap
# keeps the bubble legible; typing narrows the set. (A compact multi-column grid
# that shows more would need a new C++ slot type — tracked as a follow-up.)
_MAX_GRID = 9
LIBRARY_BUBBLE_PREFIX = "libbrowse:"
LIB_ADD_PREFIX = "lib_add:"

# Enrolled-library asset index: [{name, library, blend_file, type}]. Cached
# because the scan opens every .blend on the main thread; rebuilt on mode entry
# and whenever invalidate() is called (e.g. after a train).
_asset_cache = None

# In-flight semantic search: a token discards stale results when the user types
# a new query before the previous request returns.
_search_token = 0
_search_thread = None
_search_payload = None  # (token, query, had_image, {"success", "message", "results"})


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


def _is_library_bubble(msg) -> bool:
    """OUR library-browse bubble: the id prefix, or library-add action buttons."""
    if (getattr(msg, "bubble_id", "") or "").startswith(LIBRARY_BUBBLE_PREFIX):
        return True
    for action in getattr(msg, "action_items", []):
        if (getattr(action, "value", "") or "").startswith(LIB_ADD_PREFIX):
            return True
    return False


def _is_asset_card_bubble(msg) -> bool:
    """ANY asset-card bubble — ours OR a stale agent asset-picker (its action
    items carry an ``asset_name``). Used to sweep leftover cards so a previous
    search's card can't linger under the current result."""
    if _is_library_bubble(msg):
        return True
    for action in getattr(msg, "action_items", []):
        if getattr(action, "asset_name", ""):
            return True
    return False


def _agent_awaiting_input(scene) -> bool:
    """True when the agent is paused on a live question — then a picker bubble is
    real and must NOT be swept. Defaults to False (safe to sweep) if unknown; the
    caller only sweeps NON-library cards when this is False."""
    try:
        from ..constants import SessionState
        from .session import get_session_manager
        return get_session_manager().get_state(scene) == SessionState.AWAITING_INPUT
    except Exception:
        return False


def _grid_bubble(scene):
    """The ONE library bubble, updated in place. Keeps the newest library bubble
    and removes every OTHER asset-card bubble (extra library grids AND a stale
    agent asset-picker), so a fresh search fully replaces the last — the leftover
    card under a 'No matches' result. A LIVE agent picker (awaiting input) is
    left alone."""
    protect_pickers = _agent_awaiting_input(scene)
    keep = None
    for i in range(len(scene.mixie_chat_messages) - 1, -1, -1):
        msg = scene.mixie_chat_messages[i]
        ours = _is_library_bubble(msg)
        if ours and keep is None:
            keep = msg
            continue
        if ours or (_is_asset_card_bubble(msg) and not protect_pickers):
            _cleanup_bubble(msg)
            scene.mixie_chat_messages.remove(i)
    if keep is None:
        keep = scene.mixie_chat_messages.add()
        keep.bubble_id = f"{LIBRARY_BUBBLE_PREFIX}{uuid.uuid4().hex[:8]}"
        keep.sender = "AGENT"
        keep.message_type = "AGENT"
    return keep


def _cleanup_bubble(bubble) -> None:
    """Free the thumbnail images a grid bubble generated."""
    try:
        from . import asset_choice_previews
        asset_choice_previews.cleanup_bubble(bubble)
    except Exception:
        pass


def _set_content(msg, content: str) -> None:
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


def _debug_dump(scene, label: str) -> None:
    """Log the full chat-bubble state so we can see exactly what lingers."""
    try:
        msgs = scene.mixie_chat_messages
        parts = []
        for m in msgs:
            bid = (getattr(m, "bubble_id", "") or "")[:22]
            acts = list(getattr(m, "action_items", []))
            asset_n = sum(1 for a in acts if getattr(a, "asset_name", ""))
            libadd = sum(
                1 for a in acts
                if (getattr(a, "value", "") or "").startswith(LIB_ADD_PREFIX)
            )
            content = (getattr(m, "content", "") or "").replace("\n", " ")[:30]
            parts.append(
                f"<id={bid!r} acts={len(acts)} asset={asset_n} "
                f"libadd={libadd} sender={getattr(m,'sender','?')} "
                f"input={getattr(m,'input_type','')!r} content={content!r}>"
            )
        state = "?"
        try:
            from .session import get_session_manager
            state = get_session_manager().get_state(scene).name
        except Exception:
            pass
        line = (
            f"[LibraryDbg] {label} | mode={getattr(scene, 'mixie_chat_mode', '?')} "
            f"state={state} n={len(msgs)} " + "  ".join(parts)
        )
        logger.info("%s", line)
        # Also append to a file so it's easy to capture without a console.
        try:
            import os
            path = os.path.join(os.path.expanduser("~"), "mixar_library_debug.log")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass
    except Exception:
        logger.exception("[LibraryDbg] dump failed")


def build_library_grid(
    context, query: str = "", force: bool = False, header_note: str = "",
) -> None:
    """(Re)build the in-chat asset grid from the LOCAL library scan.

    Used for the empty-query "browse everything" view and as the offline
    fallback when the backend semantic search is unavailable (``header_note``
    then says so). A typed query normally goes through
    ``_start_semantic_search`` instead. Everything lands in ONE reused bubble,
    so a fresh search fully replaces the prior grid, and the enumeration
    re-scans when forced or invalidated (e.g. after a train).
    """
    scene = context.scene
    if not hasattr(scene, "mixie_chat_messages"):
        return
    query = (query or "").strip()

    _debug_dump(scene, f"build_library_grid ENTER query={query!r} force={force}")

    assets = _enumerate_assets(context, force=force)
    msg = _grid_bubble(scene)
    _cleanup_bubble(msg)
    msg.action_items.clear()
    _debug_dump(scene, f"build_library_grid AFTER _grid_bubble kept={msg.bubble_id!r}")

    if not assets:
        _set_content(
            msg,
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
    if header_note:
        header += f"\n\n_{header_note}_"
    if len(filtered) > len(shown):
        header += f" · showing the first {len(shown)}, refine your search"
    if not shown:
        _set_content(msg, header + "\n\nNo matches — try a different search.")
        _debug_dump(scene, "build_library_grid EXIT no-match")
        _redraw()
        return

    _set_content(msg, header + "\n\nClick an asset to add it to the scene at the 3D cursor.")
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


def _pending_query_image(context):
    """First pending chat attachment as ``(filename, bytes, mime)``, else None.

    Main thread only (touches bpy.data / disk). FILE attachments are read
    straight from disk; BLEND_DATA ones go through the browser panel's
    ``_extract_search_image_bytes`` (packed data, else a temp save_render),
    so both search boxes send the backend the same kind of query image.
    """
    attachments = getattr(context.scene, "mixie_chat_pending_attachments", None)
    if not attachments or len(attachments) == 0:
        return None
    att = attachments[0]
    try:
        if att.image_source == 'FILE':
            path = Path(bpy.path.abspath(att.image_path or ""))
            if not path.is_file():
                logger.warning("[LibraryMode] attachment missing: %s", path)
                return None
            import mimetypes
            mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            return (path.name, path.read_bytes(), mime)
        img = bpy.data.images.get(att.image_path)
        if img is None:
            return None
        from mixar.modules.asset_search.ui.operators.asset_search_ops import (
            _extract_search_image_bytes,
        )
        data = _extract_search_image_bytes(img)
        if not data:
            return None
        return ("search_query.jpg", data, "image/jpeg")
    except Exception:
        logger.exception("[LibraryMode] could not read attached search image")
        return None


def execute_library_mode(operator, context):
    """Composer send in LIBRARY mode. Empty text browses everything (local
    scan); typed text and/or an attached image runs the SAME backend semantic
    search as the asset browser panel, so both search boxes return the same
    assets."""
    scene = context.scene
    query = (getattr(scene, "mixie_chat_input", "") or "").strip()
    image_pack = _pending_query_image(context)
    if query or image_pack:
        _start_semantic_search(context, query, image_pack=image_pack)
    else:
        build_library_grid(context, "", force=False)
    try:
        scene.mixie_chat_input = ""  # clear the composer
        # Deselect moodboard-origin attachments BEFORE clearing, or the
        # moodboard polling sync re-adds them on the next tick (same order
        # as the agent send path).
        try:
            from mixar.modules.moodboard.core.chat_sync import (
                deselect_all_moodboard_origin_attachments,
            )
            deselect_all_moodboard_origin_attachments(scene)
        except Exception:  # noqa: BLE001 — moodboard module may not be loaded
            pass
        scene.mixie_chat_pending_attachments.clear()
    except Exception:
        pass
    return {'FINISHED'}


# --------------------------------------------------------------------------- #
# Semantic search (backend /asset-search/search — same as the browser panel)
# --------------------------------------------------------------------------- #

def _start_semantic_search(context, query: str, image_pack=None) -> None:
    """Kick a background semantic search and show a searching state.

    ``image_pack`` is an optional ``(filename, bytes, mime)`` query image —
    resolved on the main thread already, so the worker thread never touches
    bpy data.
    """
    global _search_token, _search_thread
    _search_token += 1
    token = _search_token

    scene = context.scene
    msg = _grid_bubble(scene)
    _cleanup_bubble(msg)
    msg.action_items.clear()
    if query and image_pack:
        status = f"Searching your library for “{query}” + attached image…"
    elif image_pack:
        status = "Searching your library by attached image…"
    else:
        status = f"Searching your library for “{query}”…"
    _set_content(msg, status)
    _redraw()

    _search_thread = threading.Thread(
        target=_semantic_search_worker, args=(query, token, image_pack),
        daemon=True,
    )
    _search_thread.start()
    # A rapid second search can land while the previous poll timer is still
    # registered — re-registering the same function raises.
    if not bpy.app.timers.is_registered(_poll_semantic_search):
        bpy.app.timers.register(_poll_semantic_search, first_interval=0.2)


def _semantic_search_worker(query: str, token: int, image_pack=None) -> None:
    """Background thread: POST /asset-search/search (no bpy access here)."""
    global _search_payload
    had_image = image_pack is not None
    try:
        from mixar.modules.asset_search.constants import ASSET_SEARCH_ENDPOINT
        from mixar.modules.asset_search.core.api_client import metered_client

        # Credit-metered per call — never auto-retried (see core/api_client).
        client = metered_client()
        files = {"image": image_pack} if image_pack else None
        resp = client.post(
            ASSET_SEARCH_ENDPOINT,
            data={"prompt": query, "top_k": str(_MAX_GRID)},
            files=files,
            timeout=30,
            raise_for_status=False,
        )
        if not resp.success:
            _search_payload = (token, query, had_image, {
                "success": False,
                "message": resp.message or f"Server returned {resp.status_code}",
            })
            return
        inner = (resp.data or {}).get("data", resp.data or {})
        rows = []
        for r in inner.get("results", []):
            meta = r.get("metadata", {}) or {}
            rows.append({
                "name": meta.get("name") or r.get("model_name", "?"),
                "score": float(r.get("similarity_score", 0) or 0),
                "library": meta.get("library", ""),
                "blend_file": meta.get("blend_file", ""),
                "type": meta.get("type", ""),
            })
        _search_payload = (token, query, had_image, {"success": True, "results": rows})
    except Exception as exc:  # noqa: BLE001 — worker must never raise
        _search_payload = (token, query, had_image, {"success": False, "message": str(exc)})


def _poll_semantic_search():
    """Main-thread timer: apply the finished search to the grid bubble."""
    global _search_payload
    if _search_thread is not None and _search_thread.is_alive():
        return 0.2
    payload = _search_payload
    _search_payload = None
    if payload is None:
        return None
    token, query, had_image, result = payload
    if token != _search_token:
        return None  # a newer search superseded this one

    context = bpy.context
    scene = getattr(context, "scene", None)
    if scene is None or getattr(scene, "mixie_chat_mode", "") != 'LIBRARY':
        return None

    if not result.get("success"):
        # Backend unavailable (offline, not trained, stale model) — fall back
        # to the local name filter so the tab still works, and say so. An
        # image-only query has no text to name-match, so just report the
        # failure instead of dumping the whole library as fake "matches".
        note = result.get("message") or "search unavailable"
        logger.warning("[LibraryMode] semantic search failed: %s", note)
        if had_image and not query:
            msg = _grid_bubble(scene)
            _cleanup_bubble(msg)
            msg.action_items.clear()
            _set_content(
                msg,
                f"**Image search unavailable** ({note}).\n\n"
                "Try again in a moment, or type a text search instead.",
            )
            _redraw()
            return None
        build_library_grid(
            context, query, force=False,
            header_note=f"Showing name matches only ({note}).",
        )
        return None

    _apply_semantic_results(
        context, query, result.get("results") or [], had_image=had_image,
    )
    return None


def _apply_semantic_results(
    context, query: str, rows: list, had_image: bool = False,
) -> None:
    """Render backend hits (same identity tuple as the browser panel) as the
    clickable thumbnail grid."""
    scene = context.scene
    msg = _grid_bubble(scene)
    _cleanup_bubble(msg)
    msg.action_items.clear()

    if query and had_image:
        what = f"“{query}” + your image"
    elif had_image:
        what = "your image"
    else:
        what = f"“{query}”"

    usable = [r for r in rows if r.get("name") and r.get("blend_file")][:_MAX_GRID]
    if not usable:
        _set_content(
            msg,
            f"**0** asset(s) matching {what}\n\n"
            "No matches — try a different search.",
        )
        _redraw()
        return

    _set_content(
        msg,
        f"**{len(usable)}** asset(s) matching {what}\n\n"
        "Click an asset to add it to the scene at the 3D cursor.",
    )
    for i, row in enumerate(usable):
        action = msg.action_items.add()
        score = max(0.0, min(1.0, float(row.get("score", 0.0))))
        action.label = f"{row['name']} · {int(round(score * 100))}%"
        action.value = f"{LIB_ADD_PREFIX}{i}"
        action.style = "DEFAULT"
        action.asset_name = row["name"]
        action.library = row.get("library", "")
        action.blend_file = row.get("blend_file", "")
        action.asset_type = row.get("type", "")

    try:
        from . import asset_choice_previews
        asset_choice_previews.schedule(scene, msg)
    except Exception:
        logger.exception("[LibraryMode] preview scheduling failed")

    scene.mixie_chat_user_has_engaged = True
    _redraw()


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


def _accumulate_bbox_points(ob, xform, depth, pts):
    """World-space bound-box corners for *ob*, recursing THROUGH collection
    instancers (BlenderKit-style assets hide geometry behind an EMPTY instancer,
    so a naive AABB sees nothing and the import lands unscaled at the origin)."""
    import mathutils

    if ob.type in _MEASURABLE and len(ob.bound_box):
        m = xform @ ob.matrix_world
        pts.extend(m @ mathutils.Vector(c) for c in ob.bound_box)
    if (ob.type == "EMPTY" and depth < 4
            and getattr(ob, "instance_type", "") == "COLLECTION"
            and getattr(ob, "instance_collection", None) is not None):
        ic = ob.instance_collection
        inner = (xform @ ob.matrix_world
                 @ mathutils.Matrix.Translation(-mathutils.Vector(ic.instance_offset)))
        for child in ic.all_objects:
            _accumulate_bbox_points(child, inner, depth + 1, pts)


def _world_bbox(objs):
    """Aggregate world AABB (min/max tuples) over *objs*, instancer-aware."""
    import mathutils

    pts = []
    identity = mathutils.Matrix.Identity(4)
    for ob in objs:
        _accumulate_bbox_points(ob, identity, 0, pts)
    return pts


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

        # Realize collection-instance empties (BlenderKit-style assets keep their
        # geometry behind instancers — unrealized they read as ~zero-size and
        # land at the origin). Linked duplicates, so mesh data is shared/cheap.
        instancers = [
            o for o in members
            if o.type == "EMPTY"
            and getattr(o, "instance_type", "") == "COLLECTION"
            and getattr(o, "instance_collection", None) is not None
        ]
        if instancers:
            try:
                view_layer = context.view_layer
                for o in list(context.selected_objects):
                    o.select_set(False)
                for o in instancers:
                    o.select_set(True)
                view_layer.objects.active = instancers[0]
                before = set(bpy.data.objects)
                bpy.ops.object.duplicates_make_real(
                    use_base_parent=True, use_hierarchy=True
                )
                members.extend(o for o in bpy.data.objects if o not in before)
                for o in list(context.selected_objects):
                    o.select_set(False)
                context.view_layer.update()
            except Exception:
                pass  # fall back to the instancer-aware bbox below

        # Move so the aggregate footprint's bottom-centre sits at the 3D cursor.
        member_set = set(members)
        roots = [o for o in members if o.parent is None or o.parent not in member_set]
        pts = _world_bbox(members)
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

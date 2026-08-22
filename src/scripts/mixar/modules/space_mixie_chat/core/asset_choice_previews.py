# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Local preview thumbnails for the chat asset-picker (multi-match HITL).

When the agent finds several library assets matching one object, the choice
interrupt's action buttons carry asset identities (asset_name / library /
blend_file). This module resolves each identity to a small preview image in
``bpy.data.images`` so the C++ chat UI can draw the buttons as clickable
thumbnails:

1. Append the asset datablock from its library .blend.
2. Prefer the EMBEDDED asset preview (``id.preview`` pixels) when present.
3. Fall back to a fresh 256x256 EEVEE render (same rig the embedding-training
   previews use, via asset_search.utils.preview_render).

Generation runs ONE asset per ``bpy.app.timers`` tick so the question paints
immediately as text buttons and thumbnails pop in without a long main-thread
stall. Images are transient: never packed, never saved, removed when the
picker is answered (actions slot replaced) or when a sweep finds them
unreferenced.
"""

import hashlib

import bpy

from mixar.config.logging_config import get_logger

from .ui_utils import bump_layout_epoch

logger = get_logger(__name__)

# Prefix identifying picker thumbnails in bpy.data.images (cleanup key).
IMAGE_PREFIX = "MIXAR_ASSETCHOICE_"

# Fallback-render resolution — small keeps the main-thread stall short.
RENDER_SIZE = 256

# Pending work: list of (scene_name, bubble_id, action_value, candidate dict).
_queue = []
_timer_running = False


def image_name_for(candidate):
    """Deterministic bpy image name for an asset identity (idempotent regen)."""
    key = "{}|{}|{}".format(
        candidate.get("library", ""),
        candidate.get("blend_file", ""),
        candidate.get("asset_name", ""),
    )
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return IMAGE_PREFIX + digest


def schedule(scene, bubble):
    """Resolve/queue previews for every asset option on *bubble*.

    LAYOUT IS RESERVED UP FRONT: every asset action gets its deterministic
    image name immediately — the C++ layout keys the thumbnail-sized row on
    ``image[0] != '\\0'`` (a not-yet-generated image just draws blank in the
    reserved square), so cards render at their FINAL size from the first frame
    and lazily filling thumbnails never reflows the bubble. Previously rows
    started at text height and grew one by one as images landed, making the
    grid jump on every tick. Generation failure clears the name, collapsing
    that one row back to a text button (single reflow, rare).
    """
    global _timer_running

    queued = 0
    for action in bubble.action_items:
        if not (action.asset_name and action.blend_file):
            continue
        candidate = {
            "asset_name": action.asset_name,
            "library": action.library,
            "blend_file": action.blend_file,
            # 'Collection' vs mesh types — picks the right datablock when the
            # .blend contains BOTH a collection asset and a same-named object.
            "type": action.asset_type,
        }
        name = image_name_for(candidate)
        action.image = name  # reserve the thumbnail row NOW (skeleton)
        if bpy.data.images.get(name) is not None:
            continue  # already generated — paints immediately
        _queue.append((scene.name, bubble.bubble_id, action.value, candidate))
        queued += 1

    bump_layout_epoch(scene)
    if queued and not _timer_running:
        _timer_running = True
        bpy.app.timers.register(_process_next, first_interval=0.05)
    logger.debug(
        "[AssetChoice] scheduled %d preview(s) for bubble %s",
        queued, bubble.bubble_id,
    )


def _process_next():
    """Timer callback: generate ONE queued preview, reschedule if more remain."""
    global _timer_running

    if not _queue:
        _timer_running = False
        return None

    scene_name, bubble_id, action_value, candidate = _queue.pop(0)
    try:
        name = _generate(candidate)
    except Exception:
        logger.exception(
            "[AssetChoice] preview generation failed for %s",
            candidate.get("asset_name", "?"),
        )
        name = None

    if name:
        try:
            _assign_image(scene_name, bubble_id, action_value, name)
        except Exception:
            logger.exception("[AssetChoice] could not assign preview image")
    else:
        # Generation failed and the row's height was reserved at schedule()
        # time — clear the name so this one row collapses to a text button
        # instead of showing a permanently blank square.
        try:
            _assign_image(scene_name, bubble_id, action_value, "")
        except Exception:
            logger.exception("[AssetChoice] could not clear reserved preview")

    if _queue:
        return 0.05
    # Latch reset on the LAST item too — resetting only on the empty-at-entry
    # branch left _timer_running stuck True after a round completed, so the
    # NEXT picker's schedule() never restarted the timer and its previews
    # never generated (second-picker no-images bug).
    _timer_running = False
    return None


def _assign_image(scene_name, bubble_id, action_value, image_name):
    """Write the generated image name onto the matching action item."""
    scene = bpy.data.scenes.get(scene_name)
    if scene is None:
        return
    messages = getattr(scene, "mixie_chat_messages", None)
    if messages is None:
        return
    for msg in messages:
        if getattr(msg, "bubble_id", "") != bubble_id:
            continue
        for action in msg.action_items:
            if action.value == action_value:
                action.image = image_name
        break
    bump_layout_epoch(scene)
    _redraw_chat_regions()


def _redraw_chat_regions():
    wm = bpy.context.window_manager
    if not wm:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in {'MIXIE_CHAT', 'AGENT_BUBBLE'}:
                area.tag_redraw()


def _resolve_blend_path(candidate):
    """Locate the asset's .blend on disk from the configured libraries."""
    library_name = candidate.get("library", "")
    blend_file = (candidate.get("blend_file", "") or "").replace("\\", "/")
    if not blend_file or ".." in blend_file.split("/"):
        return None
    for lib in bpy.context.preferences.filepaths.asset_libraries:
        if lib.name == library_name:
            root = lib.path.replace("\\", "/").rstrip("/")
            return root + "/" + blend_file.lstrip("/")
    return None


def _extract_embedded_preview(id_block, image_name):
    """Build a bpy image from the datablock's embedded asset preview.

    Returns the image name, or None when the preview is missing/empty.
    (Never calls preview_ensure() — that creates an empty struct, it does
    not render a preview.)
    """
    prev = getattr(id_block, "preview", None)
    if prev is None:
        return None
    width, height = prev.image_size[0], prev.image_size[1]
    if width <= 0 or height <= 0:
        return None

    pixel_count = width * height * 4
    buf = [0.0] * pixel_count
    try:
        prev.image_pixels_float.foreach_get(buf)
    except Exception:
        return None
    if not any(buf):
        return None  # all-zero = never actually generated

    img = bpy.data.images.new(image_name, width, height, alpha=True)
    img.pixels.foreach_set(buf)
    return img.name


def _generate(candidate):
    """Produce the preview image for one asset. Returns the image name or None.

    Appends the datablock, tries the embedded preview, falls back to a fresh
    256x256 EEVEE render, then removes the appended data.
    """
    from mixar.modules.asset_search.utils.preview_render import (
        PreviewRenderRig,
        frame_camera,
        remove_collection,
        remove_objects,
        render_to_image,
    )

    name = image_name_for(candidate)
    if bpy.data.images.get(name) is not None:
        return name

    blend_path = _resolve_blend_path(candidate)
    if not blend_path:
        logger.warning(
            "[AssetChoice] could not resolve library path for %s",
            candidate.get("asset_name", "?"),
        )
        return None

    asset_name = candidate["asset_name"]
    # A collection asset's .blend usually ALSO contains a same-named member
    # object — probing objects first then appended the WRONG datablock (no
    # embedded preview on it → blank thumbnails). The search metadata's type
    # says which one the asset actually is.
    prefer_collection = (candidate.get("type") or "").lower().startswith("collection")

    # Append the datablock (object or collection, type-aware preference).
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        in_objects = asset_name in data_from.objects
        in_collections = asset_name in getattr(data_from, "collections", [])
        if in_collections and (prefer_collection or not in_objects):
            data_to.collections = [asset_name]
        elif in_objects:
            data_to.objects = [asset_name]
        else:
            logger.warning(
                "[AssetChoice] '%s' not found in %s", asset_name, blend_path,
            )
            return None

    appended_obj = data_to.objects[0] if data_to.objects else None
    appended_coll = data_to.collections[0] if data_to.collections else None
    id_block = appended_obj or appended_coll
    if id_block is None:
        return None

    scene = bpy.context.scene
    scene_coll = scene.collection

    try:
        # 1. Embedded asset preview (cheap, no render).
        result = _extract_embedded_preview(id_block, name)
        if result:
            return result

        # 2. Fresh render fallback (same rig as embedding training, smaller).
        render_objs = (
            [appended_obj] if appended_obj else list(appended_coll.all_objects)
        )
        # A render of nothing produces an all-black JPEG that reads as a blank
        # button — a plain text button is better. Only render when there is
        # something visible (meshes/curves, or collection-instancer empties).
        renderable = any(
            o.type in {"MESH", "CURVE", "SURFACE", "META", "FONT"}
            or (
                o.type == "EMPTY"
                and getattr(o, "instance_type", "") == "COLLECTION"
                and getattr(o, "instance_collection", None) is not None
            )
            for o in render_objs
        )
        if not renderable:
            logger.warning(
                "[AssetChoice] '%s' has no renderable geometry — leaving a "
                "text-only button", asset_name,
            )
            return None
        if appended_obj:
            if appended_obj.name not in scene_coll.objects:
                scene_coll.objects.link(appended_obj)
        else:
            if appended_coll.name not in scene_coll.children:
                scene_coll.children.link(appended_coll)

        # This runs from a bpy.app.timers callback, where bpy.context has no
        # window — bpy.ops.render.render() can fail its poll there. Override
        # with a real window (any) so the operator has a full context.
        win = bpy.context.window
        if win is None:
            wm = bpy.context.window_manager
            win = wm.windows[0] if wm and wm.windows else None

        with PreviewRenderRig(scene, size=RENDER_SIZE) as rig:
            frame_camera(rig.camera, render_objs)
            if win is not None:
                with bpy.context.temp_override(
                    window=win, screen=win.screen, scene=scene
                ):
                    img = render_to_image(scene, name, pack=False)
            else:
                img = render_to_image(scene, name, pack=False)
        return img.name if img else None
    finally:
        # Remove the appended datablocks — the picker must not mutate the scene.
        try:
            if appended_coll is not None:
                if appended_coll.name in scene_coll.children:
                    scene_coll.children.unlink(appended_coll)
                remove_collection(appended_coll)
            elif appended_obj is not None:
                remove_objects([appended_obj])
        except Exception:
            logger.exception("[AssetChoice] cleanup of appended asset failed")


def cleanup_bubble(bubble):
    """Remove this bubble's preview images unless another bubble still uses them."""
    names = {item.image for item in bubble.action_items if item.image}
    if not names:
        return
    still_used = _images_in_use(exclude_bubble_id=bubble.bubble_id)
    for name in names - still_used:
        img = bpy.data.images.get(name)
        if img is not None:
            bpy.data.images.remove(img)


def cleanup_orphans(scene=None):
    """Sweep ALL picker images that no bubble references (new message /
    session clear)."""
    used = _images_in_use()
    for img in list(bpy.data.images):
        if img.name.startswith(IMAGE_PREFIX) and img.name not in used:
            bpy.data.images.remove(img)


def _images_in_use(exclude_bubble_id=None):
    """Collect preview image names referenced by any bubble's action items."""
    used = set()
    for scene in bpy.data.scenes:
        messages = getattr(scene, "mixie_chat_messages", None)
        if messages is None:
            continue
        for msg in messages:
            if exclude_bubble_id and getattr(msg, "bubble_id", "") == exclude_bubble_id:
                continue
            for action in getattr(msg, "action_items", []):
                if action.image:
                    used.add(action.image)
    return used

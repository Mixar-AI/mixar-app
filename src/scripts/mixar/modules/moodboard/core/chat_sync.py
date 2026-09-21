# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard → Chat composer sync.

Mirrors the currently-selected moodboard stills (including selected frames
and generated results) into ``scene.mixie_chat_pending_attachments`` so the
agent sees them on the next send. One-way: board selection drives the
composer. Deselecting an image, frame or node removes its moodboard-origin
pill; manual FILE / blend-data attachments are left untouched. Identity
and the ten-reference cap are shared with those manual pills.

**Why polling instead of a property update= callback:**
The moodboard's click / box-select / cmd-click operators are
implemented in C++ (``src/source/blender/editors/space_mixie/
mixie_moodboard_ops_*.cc``) and call ``RNA_property_boolean_set``
directly *without* a follow-up ``RNA_property_update``. Blender's
``update=`` callback machinery only fires from the latter path, so
a property-side callback misses every selection change made by the
operators users actually use. A tiny polling tick that diffs a
"selection signature" against the last-seen value is robust against
every code path that mutates selection (Python, C++, scripts) and
costs effectively nothing when nothing has changed.

**Undo note:**
Mutations to ``pending_attachments`` happen from a ``bpy.app.timers``
callback, not from an operator. Blender's undo stack is operator-
driven (operators with ``'UNDO'`` in ``bl_options`` capture state on
completion), so timer-driven mutations don't push their own undo
steps — they're transparently rolled back as part of whatever
operator-captured snapshot the user reverts to. We deliberately
don't wrap the mutations in an internal operator to keep the call
path simple.
"""

from __future__ import annotations

from typing import Iterable

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from .chat_sync_dedupe import (
    board_image_is_attached,
    attachment_identity_sets,
)
from .chat_sync_deselect import (
    deselect_all_moodboard_origin_attachments,
    deselect_moodboard_image_by_name,
    deselect_moodboard_image_for_attachment,
)
from .media_utils import is_video_item

_logger = get_logger(__name__)

# Poll cadence. 200ms is well under any human-perceptible "this should
# have updated by now" threshold while keeping the cost trivial.
_POLL_INTERVAL_S = 0.2

# Per-scene cache of the last selection signature we synced. Keyed by
# scene.name (Blender's scene name is unique within a file). Avoids
# spurious cross-scene resync when the user switches scenes, and
# tolerates multiple scenes that each have their own moodboard.
_last_signatures: dict[str, tuple] = {}


# ----------------------------------------------------------------- #
# Selection collection (honors both direct image selection and frame
# selection, mirroring the manual MIXIE_OT_moodboard_send_to_chat).
# ----------------------------------------------------------------- #
def _selected_frame_ids(scene) -> set[str]:
    """Ids of every selected canvas frame.

    Frames replaced the index-based ``mixie_moodboard_groups`` collection,
    which ``frames.migrate_legacy_groups`` empties permanently on load — so
    membership is read from ``frame_id`` here, never from ``group_index``.
    """
    return {
        frame.frame_id
        for frame in getattr(scene, "mixie_moodboard_frames", ()) or ()
        if getattr(frame, "selected", False) and getattr(frame, "frame_id", "")
    }


def _collect_selected_image_names(scene) -> list[str]:
    """Return sorted unique ``bpy.data.images.name`` for every moodboard
    image that should be attached. Includes:
      * directly selected images
      * every image inside a SELECTED frame

    Deliberately NOT the reverse: selecting one picture inside a frame
    attaches that picture, not its neighbours. That is the same rule
    ``get_all_items_to_transform`` applies to dragging — clicking a thing
    acts on that thing, and the frame is selected by its own border — and
    it is what the frame rewrite replaced the old group cohesion with.
    """
    images_attr = getattr(scene, "mixie_moodboard_images", None)
    if images_attr is None:
        return []

    # 1. Frames whose whole contents ride along.
    selected_frame_ids = _selected_frame_ids(scene)

    # 2. Collect names.
    names: set[str] = set()
    for mb_img in images_attr:
        img = mb_img.image
        # Chat attachments are still-image-only today. Keep videos selected on
        # the board for the future Seedance path without flattening a movie to
        # a misleading single-frame chat attachment.
        if img is None or is_video_item(mb_img):
            continue
        if mb_img.selected:
            names.add(img.name)
        elif (
            selected_frame_ids
            and getattr(mb_img, "frame_id", "") in selected_frame_ids
        ):
            names.add(img.name)

    # 3. Selected inference nodes contribute their generated still output.
    # A node's output lives as an *embedded* media item (its `.selected` is
    # pinned False, node_graph.connect_image_result) plus `node.preview_image`,
    # and clicking a node flips `node.selected` instead of any media item's
    # flag. Without this, a selected generated node — unlike a selected upload —
    # never reaches the agent. Videos/3D previews are skipped (attachments are
    # still-image-only, and model nodes carry a preview_object, not an image).
    nodes_attr = getattr(scene, "mixie_moodboard_action_nodes", None)
    if nodes_attr is not None:
        for node in nodes_attr:
            if not getattr(node, "selected", False):
                continue
            preview = getattr(node, "preview_image", None)
            if preview is None or getattr(preview, "source", "") == 'MOVIE':
                continue
            names.add(preview.name)

    return sorted(names)


def _compute_selection_signature(scene) -> tuple:
    """Desired attachment state for this scene, including moodboard-origin count.

    The count detects drift when send/clear empties ``pending_attachments``
    while the board selection has not changed.
    """
    names = tuple(_collect_selected_image_names(scene))

    attachments = getattr(scene, "mixie_chat_pending_attachments", None)
    mb_att_count = 0
    if attachments is not None:
        for att in attachments:
            if getattr(att, "is_moodboard", False):
                mb_att_count += 1

    return (mb_att_count, names)


# ----------------------------------------------------------------- #
# Reconciliation (single-pass, atomic-ish)
# ----------------------------------------------------------------- #
def _reconcile_attachments(scene, target_names: Iterable[str], *, animate=False) -> None:
    """Make moodboard-origin attachments equal ``target_names``, up to the cap.

    Manual FILE / non-moodboard BLEND_DATA pills are never touched. A
    BLEND_DATA pill matches by image name; a FILE pill matches when the
    board image was loaded from that file. Overflow stays selected and
    attaches when the user deselects something or frees a slot.
    """
    from mixar.modules.space_mixie_chat.constants import MAX_ATTACHMENTS_PER_MESSAGE

    attachments = getattr(scene, "mixie_chat_pending_attachments", None)
    if attachments is None:
        return
    target_set = set(target_names)
    blend_names, file_keys = attachment_identity_sets(attachments)
    to_remove = [
        i for i, att in enumerate(attachments)
        if getattr(att, "is_moodboard", False) and att.image_path not in target_set
    ]
    keeps = {
        att.image_path for att in attachments
        if getattr(att, "is_moodboard", False) and att.image_path in target_set
    }
    to_add = [
        name for name in sorted(target_set)
        if name not in keeps
        and not board_image_is_attached(name, blend_names, file_keys)
    ]
    if not to_remove and not to_add:
        return
    for i in reversed(to_remove):
        attachments.remove(i)
    added = to_add[: max(0, MAX_ATTACHMENTS_PER_MESSAGE - len(attachments))]
    for name in added:
        att = attachments.add()
        att.image_path = name
        att.image_source = 'BLEND_DATA'
        att.display_name = name
        att.is_moodboard = True
    if animate and added:
        from .attachment_motion import animate_attachments
        animate_attachments(scene, added)
    _redraw_chat_areas()


# ----------------------------------------------------------------- #
# Polling tick
# ----------------------------------------------------------------- #
def _ensure_graph_node_ids(scene) -> None:
    """Backfill missing moodboard graph node ids. Never raises."""
    try:
        from .node_graph import ensure_media_node_ids

        ensure_media_node_ids(scene)
    except Exception as e:  # noqa: BLE001 — timer must never raise
        _logger.debug("moodboard node id migration failed: %s", e, exc_info=True)


def _migrate_legacy_frames(scene) -> None:
    """Turn a pre-frame board's index-based groups into real frames.

    Runs from the poll tick and ``load_post``, never from a draw callback, for
    the same reason the node-id migration does: it writes scene data.
    One-way and idempotent -- the legacy collection is cleared as it converts,
    so every later tick finds nothing and returns immediately.
    """
    try:
        if not getattr(scene, "mixie_moodboard_groups", None):
            return
        from .frames import migrate_legacy_groups

        migrate_legacy_groups(scene)
    except Exception as e:  # noqa: BLE001 — timer must never raise
        _logger.debug("moodboard frame migration failed: %s", e, exc_info=True)


def _restore_graph_node_selections(scene) -> None:
    """Re-derive each node's Mode/Model dropdown from its saved slugs.

    The dropdowns are dynamic enums stored as an index into the items list, so
    a freshly loaded file shows whatever that index now resolves to. The
    catalog-swap callback restores them, but only when a swap actually happens
    — opening a .blend while the catalog is already loaded produces no swap, so
    without this the node would display the wrong model (while still
    submitting the right one, which is the more confusing failure).
    """
    try:
        from .node_schema import restore_node_selection

        for node in getattr(scene, "mixie_moodboard_action_nodes", ()):
            restore_node_selection(node)
    except Exception as e:  # noqa: BLE001 — handler must never raise
        _logger.debug("moodboard node selection restore failed: %s", e, exc_info=True)


def _poll_tick():
    """bpy.app.timers callback: detect selection changes and sync.

    Must never raise — exceptions kill the timer permanently. Returns
    the next interval so the timer reschedules itself.
    """
    try:
        scene = bpy.context.scene
        if scene is None:
            return _POLL_INTERVAL_S

        # Graph node ids are minted only by this migration, and the canvas
        # lookups are read-only by design (assigning ids from a draw or
        # menu-draw path would write scene data mid-redraw). This tick is the
        # moodboard's existing main-thread hook, so it is where ids get
        # backfilled for images added by any of the collection's writers —
        # including the C++ drop operator. No-ops once every id is present.
        _ensure_graph_node_ids(scene)
        _migrate_legacy_frames(scene)

        key = scene.name
        signature = _compute_selection_signature(scene)
        if _last_signatures.get(key) == signature:
            return _POLL_INTERVAL_S

        previous = _last_signatures.get(key)
        _last_signatures[key] = signature
        _reconcile_attachments(
            scene,
            signature[1],
            animate=previous is not None and previous[1] != signature[1],
        )
    except Exception as e:  # noqa: BLE001 — timer must never raise
        _logger.debug("moodboard chat_sync poll failed: %s", e, exc_info=True)

    return _POLL_INTERVAL_S


# ----------------------------------------------------------------- #
# Public helpers
# ----------------------------------------------------------------- #
def force_resync(scene=None) -> None:
    """Drop the cached signature so the next poll runs a full sync.
    If ``scene`` is omitted, invalidates *all* per-scene caches.
    """
    if scene is None:
        _last_signatures.clear()
    else:
        _last_signatures.pop(scene.name, None)


# ----------------------------------------------------------------- #
# UI redraw — tag only, never resize the bubble
# ----------------------------------------------------------------- #
def _redraw_moodboard_areas() -> None:
    """Tag both moodboard hosts for redraw. Used when we mutate
    moodboard selection from a chat-side path (X-button on a pill,
    send completion) — without this, the moodboard's GPU-drawn
    selection rectangles keep showing the now-deselected image as
    selected until some other event (mouse move, typing into the
    composer, etc.) triggers a draw cycle."""
    try:
        from .canvas_context import redraw_moodboard_canvases
        redraw_moodboard_canvases()
    except Exception as e:  # noqa: BLE001
        _logger.debug("moodboard redraw failed: %s", e, exc_info=True)


def _redraw_chat_areas() -> None:
    """Tag MIXIE_CHAT + AGENT_BUBBLE areas for redraw — no bubble
    resize. Forcing the bubble to grow on the rising edge of a
    selection caused a visible flash on every first-of-a-batch
    moodboard select; the composer's own draw pipeline already
    lays attachments out within the user's chosen bubble size.
    """
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'AGENT_BUBBLE'}:
                    area.tag_redraw()
    except Exception as e:  # noqa: BLE001
        _logger.debug("moodboard chat_sync redraw failed: %s", e, exc_info=True)


# ----------------------------------------------------------------- #
# Lifecycle
# ----------------------------------------------------------------- #
@persistent
def _on_file_load_post(*_args) -> None:
    """Drop stale per-scene signatures after a .blend file load.

    The freshly loaded scene starts with empty (SKIP_SAVE)
    ``pending_attachments`` but may already carry selected moodboard
    images. A signature cached from the previous file could spuriously
    match and suppress the first reconcile, so we clear the cache and
    let the next poll perform a full sync.
    """
    _last_signatures.clear()
    # Old .blend files predate the graph and carry no node ids. Migrate every
    # scene once on load so a link drag started before the first poll tick
    # still resolves its source.
    try:
        for scene in bpy.data.scenes:
            _ensure_graph_node_ids(scene)
            _migrate_legacy_frames(scene)
            _restore_graph_node_selections(scene)
    except Exception as e:  # noqa: BLE001 — handler must never raise
        _logger.debug("moodboard node id load migration failed: %s", e, exc_info=True)


def register() -> None:
    """Start the polling tick. Idempotent — safe to call twice.

    The timer is registered ``persistent=True`` so it survives .blend
    file loads. Blender unregisters non-persistent timers on load, and
    ``register()`` only runs once at addon startup — a non-persistent
    tick would silently stop syncing the moment the user opens another
    file, so moodboard selections would no longer auto-attach.
    """
    _last_signatures.clear()
    if not bpy.app.timers.is_registered(_poll_tick):
        bpy.app.timers.register(
            _poll_tick, first_interval=_POLL_INTERVAL_S, persistent=True
        )
    if _on_file_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_file_load_post)


def unregister() -> None:
    """Stop the polling tick. Idempotent."""
    if _on_file_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_file_load_post)
    if bpy.app.timers.is_registered(_poll_tick):
        try:
            bpy.app.timers.unregister(_poll_tick)
        except ValueError:
            pass
    _last_signatures.clear()

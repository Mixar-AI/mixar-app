# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard → Chat composer sync.

Adds newly selected moodboard stills (including groups and generated results)
to ``scene.mixie_chat_pending_attachments``. References remain staged when the
selection changes or clears; only explicit composer removal/clear or sending
consumes them. Selection edges add references once, so attachment-count changes
cannot resurrect a removed reference or silently fill a newly freed slot.
Manual attachments share the same identity checks and five-reference limit.

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
    attachment_shows_board_item,
    board_image_is_attached,
    attachment_identity_sets,
    file_key,
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
# Selection collection (honors both direct image selection and group
# selection, mirroring the manual MIXIE_OT_moodboard_send_to_chat).
# ----------------------------------------------------------------- #
def _collect_selected_image_names(scene) -> list[str]:
    """Return sorted unique ``bpy.data.images.name`` for every moodboard
    image that should be attached. Includes:
      * directly selected images
      * all images in groups that are selected
      * all images in groups that contain at least one selected image
        (group cohesion — matches the legacy "send to chat" op)
    """
    images_attr = getattr(scene, "mixie_moodboard_images", None)
    groups_attr = getattr(scene, "mixie_moodboard_groups", None)
    if images_attr is None:
        return []

    # 1. Build the set of group indices that should pull all members.
    selected_group_indices: set[int] = set()
    if groups_attr is not None:
        for i, group in enumerate(groups_attr):
            if group.selected:
                selected_group_indices.add(i)
        # Group cohesion: any image with a selected sibling pulls the
        # whole group.
        for mb_img in images_attr:
            if mb_img.selected and mb_img.group_index >= 0:
                selected_group_indices.add(mb_img.group_index)

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
        elif mb_img.group_index in selected_group_indices:
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
    """Observed selection and attachment count, including explicit composer edits."""
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
    """Add these selection edges without removing or replacing staged references.

    Identity is shared with manual FILE/BLEND_DATA attachments. Repeated
    selection never duplicates or replays a reference; overflow is rejected,
    not queued for a surprise attach after the user removes something else.
    """
    from mixar.modules.space_mixie_chat.constants import MAX_ATTACHMENTS_PER_MESSAGE

    attachments = getattr(scene, "mixie_chat_pending_attachments", None)
    if attachments is None:
        return
    blend_names, file_keys = attachment_identity_sets(attachments)
    to_add = [name for name in sorted(set(target_names))
              if not board_image_is_attached(name, blend_names, file_keys)]
    remaining = max(0, MAX_ATTACHMENTS_PER_MESSAGE - len(attachments))
    added = to_add[:remaining]
    for name in added:
        att = attachments.add()
        att.image_path = name
        att.image_source = 'BLEND_DATA'
        att.display_name = name
        att.is_moodboard = True
    if added:
        if animate:
            from .attachment_motion import animate_attachments
            animate_attachments(scene, added)
        _redraw_chat_areas()
    if len(to_add) > remaining:
        _notify_attachment_limit(MAX_ATTACHMENTS_PER_MESSAGE)


def _notify_attachment_limit(limit):
    """A rejected selection must not look like it replaced an older reference."""
    try:
        from mixar.modules.common.notifications import get_notification_store
        get_notification_store().push(
            "warning", f"Chat reference limit reached ({limit})",
            body="Remove a reference in Agent chat, then select the image again.",
            id="chat-reference-limit",
            ttl_ms=6000,
        )
    except Exception:
        _logger.debug("Attachment limit notification unavailable", exc_info=True)


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

        key = scene.name
        signature = _compute_selection_signature(scene)
        if _last_signatures.get(key) == signature:
            return _POLL_INTERVAL_S

        previous = _last_signatures.get(key)
        names = signature[1] if previous is None else sorted(set(signature[1]) - set(previous[1]))
        _reconcile_attachments(scene, names, animate=previous is not None and bool(names))
        _last_signatures[key] = _compute_selection_signature(scene)
    except Exception as e:  # noqa: BLE001 — timer must never raise
        _logger.debug("moodboard chat_sync poll failed: %s", e, exc_info=True)

    return _POLL_INTERVAL_S


# ----------------------------------------------------------------- #
# Public helpers
# ----------------------------------------------------------------- #
def force_resync(scene=None) -> None:
    """Explicitly allow the current selection to attach again on the next poll.
    If ``scene`` is omitted, invalidates *all* per-scene caches.
    """
    if scene is None:
        _last_signatures.clear()
    else:
        _last_signatures.pop(scene.name, None)


def consume_selection(scene) -> None:
    """Record selection before an explicit clear/send so it cannot re-attach."""
    _last_signatures[scene.name] = _compute_selection_signature(scene)


def deselect_moodboard_image_for_attachment(
    scene, image_path: str, image_source: str
) -> bool:
    """Deselect every moodboard image the composer attachment
    ``(image_path, image_source)`` stands for. Returns True if at least
    one image was deselected.

    The X button consumes this reference's selection edge, including groups
    and generated nodes, and releases direct media selection. FILE references
    use the same identity rules as their selected board copies.
    """
    # Consume only this reference, including selected groups/generated nodes.
    # Other images selected since the last poll still get their normal add edge.
    previous = _last_signatures.get(scene.name, (0, ()))
    blend_names = {image_path} if image_source == 'BLEND_DATA' else set()
    file_keys = {file_key(image_path)} if image_source == 'FILE' else set()
    dismissed = {name for name in _collect_selected_image_names(scene)
                 if board_image_is_attached(name, blend_names, file_keys)}
    _last_signatures[scene.name] = (previous[0], tuple(sorted(set(previous[1]) | dismissed)))
    images_attr = getattr(scene, "mixie_moodboard_images", None)
    if images_attr is None:
        return False
    changed = False
    for mb_img in images_attr:
        if not mb_img.selected:
            continue
        if attachment_shows_board_item(mb_img, image_path, image_source):
            mb_img.selected = False
            changed = True
    if changed:
        _redraw_moodboard_areas()
    return changed


def deselect_moodboard_image_by_name(scene, image_name: str) -> bool:
    """Name-only form of :func:`deselect_moodboard_image_for_attachment`."""
    return deselect_moodboard_image_for_attachment(scene, image_name, 'BLEND_DATA')


def deselect_all_moodboard_origin_attachments(scene) -> int:
    """Deselect every moodboard image (and any groups they belong to)
    whose corresponding ``is_moodboard`` attachment is in
    ``pending_attachments``. Called from the chat send paths BEFORE
    ``pending_attachments.clear()`` so moodboard selections don't
    auto-re-attach on the next poll after the message goes out.

    Returns the number of moodboard images deselected.
    """
    consume_selection(scene)
    images_attr = getattr(scene, "mixie_moodboard_images", None)
    groups_attr = getattr(scene, "mixie_moodboard_groups", None)
    attachments = getattr(scene, "mixie_chat_pending_attachments", None)
    if images_attr is None or attachments is None:
        return 0

    moodboard_attached_names = {
        att.image_path for att in attachments
        if getattr(att, "is_moodboard", False) and att.image_path
    }
    if not moodboard_attached_names:
        return 0

    # Collect the group indices touched so we deselect groups too —
    # otherwise group cohesion would re-include their images on the
    # next poll.
    touched_groups: set[int] = set()
    count = 0
    for mb_img in images_attr:
        if mb_img.image is None:
            continue
        if mb_img.image.name in moodboard_attached_names and mb_img.selected:
            mb_img.selected = False
            if mb_img.group_index >= 0:
                touched_groups.add(mb_img.group_index)
            count += 1

    if groups_attr is not None:
        for idx in touched_groups:
            if 0 <= idx < len(groups_attr) and groups_attr[idx].selected:
                groups_attr[idx].selected = False

    if count:
        _redraw_moodboard_areas()
    return count


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
                if area.type in {'MIXIE_CHAT', 'AGENT_BUBBLE'}:
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

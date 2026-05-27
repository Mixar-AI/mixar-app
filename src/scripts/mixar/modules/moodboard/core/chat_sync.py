# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard → Chat composer sync.

Mirrors the set of currently-selected moodboard images (and images
belonging to selected groups) into ``scene.mixie_chat_pending_attachments``
so the agent automatically sees them as attachments when the next
message is sent. One-way: moodboard selection drives the composer,
not the other way around. Manually-added attachments (file picker,
screenshots, clipboard, blend-data) are left untouched — we only
own attachments whose ``is_moodboard`` flag is True.

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

from mixar.config.logging_config import get_logger

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
        if img is None:
            continue
        if mb_img.selected:
            names.add(img.name)
        elif mb_img.group_index in selected_group_indices:
            names.add(img.name)

    return sorted(names)


def _compute_selection_signature(scene) -> tuple:
    """Hashable tuple uniquely identifying the desired attachment state
    for this scene. Includes the moodboard-origin attachment count so
    we also detect drift when an external code path (e.g. the chat
    send pipeline) clears ``pending_attachments`` out from under us.
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
def _reconcile_attachments(scene, target_names: Iterable[str]) -> None:
    """Make the moodboard-origin attachments in ``pending_attachments``
    exactly equal to ``target_names``. Single pass so a mid-iteration
    RNA failure can't leave the collection half-reconciled.

    Manually-added attachments (FILE / non-moodboard BLEND_DATA) are
    never touched. Also de-dupes against existing non-moodboard
    BLEND_DATA attachments with matching path — if the user manually
    attached the same image, we don't add a moodboard copy on top of
    it. This handles the post-reload case where SKIP_SAVE wiped the
    is_moodboard flag on a previously-mirrored attachment.
    """
    attachments = getattr(scene, "mixie_chat_pending_attachments", None)
    if attachments is None:
        return

    target_set: set[str] = set(target_names)

    # Snapshot what's there so we don't mutate while iterating.
    existing_moodboard_indices: list[int] = []
    existing_paths_by_source: set[tuple[str, str]] = set()
    for i, att in enumerate(attachments):
        path = att.image_path
        source = att.image_source
        existing_paths_by_source.add((path, source))
        if getattr(att, "is_moodboard", False):
            existing_moodboard_indices.append(i)

    # Compute the operations.
    to_remove: list[int] = []  # indices in `attachments`
    to_add: list[str] = []     # image names
    keeps: set[str] = set()    # moodboard-origin names already present

    for i in existing_moodboard_indices:
        path = attachments[i].image_path
        if path in target_set:
            keeps.add(path)
        else:
            to_remove.append(i)

    for name in target_set:
        if name in keeps:
            continue
        # De-dupe against any pre-existing BLEND_DATA attachment of the
        # same name (e.g. a survivor of save/reload that lost its
        # is_moodboard flag, or a manual blend-data add).
        if (name, 'BLEND_DATA') in existing_paths_by_source:
            continue
        to_add.append(name)

    if not to_remove and not to_add:
        return

    # Apply removes high-to-low so earlier indices stay valid.
    for i in sorted(to_remove, reverse=True):
        attachments.remove(i)

    for name in to_add:
        att = attachments.add()
        att.image_path = name
        att.image_source = 'BLEND_DATA'
        att.display_name = name
        att.is_moodboard = True

    _redraw_chat_areas()


# ----------------------------------------------------------------- #
# Polling tick
# ----------------------------------------------------------------- #
def _poll_tick():
    """bpy.app.timers callback: detect selection changes and sync.

    Must never raise — exceptions kill the timer permanently. Returns
    the next interval so the timer reschedules itself.
    """
    try:
        scene = bpy.context.scene
        if scene is None:
            return _POLL_INTERVAL_S

        key = scene.name
        signature = _compute_selection_signature(scene)
        if _last_signatures.get(key) == signature:
            return _POLL_INTERVAL_S

        _last_signatures[key] = signature
        _reconcile_attachments(scene, signature[1])
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


def deselect_moodboard_image_by_name(scene, image_name: str) -> bool:
    """Deselect any moodboard images whose ``image.name`` matches.
    Returns True if at least one image was deselected.

    Called from the chat composer's X-button operator so removing a
    moodboard pill cleanly drops the moodboard's selection — without
    this, the polling tick would re-add the attachment on the next
    cycle.
    """
    images_attr = getattr(scene, "mixie_moodboard_images", None)
    if images_attr is None:
        return False
    changed = False
    for mb_img in images_attr:
        if mb_img.image is None:
            continue
        if mb_img.image.name == image_name and mb_img.selected:
            mb_img.selected = False
            changed = True
    if changed:
        force_resync(scene)
    return changed


def deselect_all_moodboard_origin_attachments(scene) -> int:
    """Deselect every moodboard image (and any groups they belong to)
    whose corresponding ``is_moodboard`` attachment is in
    ``pending_attachments``. Called from the chat send paths BEFORE
    ``pending_attachments.clear()`` so moodboard selections don't
    auto-re-attach on the next poll after the message goes out.

    Returns the number of moodboard images deselected.
    """
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
        force_resync(scene)
    return count


# ----------------------------------------------------------------- #
# UI redraw — tag only, never resize the bubble
# ----------------------------------------------------------------- #
def _redraw_chat_areas() -> None:
    """Tag MIXIE_CHAT + AGENT_BUBBLE areas only — no bubble resize.

    Earlier this called sync_bubble_attachment_size_deferred which
    forced the bubble to grow whenever an attachment changed. That
    caused visible flashing during box-select bursts and pushed the
    bubble above the empty-state's height threshold, so deselecting
    an image left the bubble grown and the "Hi I'm Mixie" greeting
    visible again. The composer's own draw pipeline handles
    attachment layout within the user's chosen bubble size; we just
    need to ask for a repaint.
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
def register() -> None:
    """Start the polling tick. Idempotent — safe to call twice."""
    _last_signatures.clear()
    if not bpy.app.timers.is_registered(_poll_tick):
        bpy.app.timers.register(_poll_tick, first_interval=_POLL_INTERVAL_S)


def unregister() -> None:
    """Stop the polling tick. Idempotent."""
    if bpy.app.timers.is_registered(_poll_tick):
        try:
            bpy.app.timers.unregister(_poll_tick)
        except ValueError:
            pass
    _last_signatures.clear()

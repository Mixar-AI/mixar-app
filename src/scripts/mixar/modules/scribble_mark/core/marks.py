# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mark store — marks as addressable scene nouns, not message contents.

A mark that lives only in one turn's message dies to context compaction, and
"make it a bit taller" three turns later then has nothing to resolve against.
So every mark is written into the .blend: a record here, a baked camera, and
(for a partial selection) a vertex group. The agent can come back to any of
them by name.

``get_marks()`` is the sandbox entry point, mirroring the pattern the sketch
pipeline uses::

    from mixar.modules.scribble_mark.core import marks
    data = marks.get_marks()

so a lane re-reads the marks rather than relying on them surviving in context.

Structured fields are stored as JSON strings rather than nested
PropertyGroups. The payload shape is versioned and shared with the backend
schema; mirroring it into RNA would give it a second, silently diverging
definition, and the .blend would need a migration every time a field moved.
"""

from __future__ import annotations

import json

import bpy

from mixar.config.logging_config import get_logger

from . import freeze, view_bake, vertex_groups
from . import payload as payload_mod
from ..constants import (
    MARK_PAYLOAD_VERSION,
    MAX_MARKS_PER_TURN,
    SURFACE_VIEW3D,
)

logger = get_logger(__name__)

STATE_DRAFT = "DRAFT"
STATE_SENT = "SENT"


# =============================================================================
# Writing
# =============================================================================

def next_serial(scene):
    """Next mark serial for this scene. Monotonic within a .blend.

    Never reuses a number even after marks are cleared: a vertex group or
    camera from an earlier mark may still be referenced in the conversation,
    and reusing its name would silently repoint that reference.
    """
    serial = int(getattr(scene, "mixar_mark_serial", 0)) + 1
    scene.mixar_mark_serial = serial
    return serial


def add_mark(scene, serial, view_name, view_data, reading, region_width,
             region_height, resolved=None):
    """Record one mark. Returns the stored item, or None if it did not fit."""
    collection = _collection(scene)
    if collection is None:
        return None

    # Drafts only. Counting every mark ever made would let eight sent marks
    # permanently disable the feature for the rest of the .blend's life.
    if sum(1 for i in collection if i.state == STATE_DRAFT) >= MAX_MARKS_PER_TURN:
        logger.info("Scribble mark: refusing mark %d, already at the cap of %d",
                    serial, MAX_MARKS_PER_TURN)
        return None

    try:
        built = payload_mod.build_mark(
            serial, view_name, reading, region_width, region_height, resolved
        )
    except ValueError as exc:
        logger.warning("Scribble mark: could not build mark %d: %s", serial, exc)
        return None

    item = collection.add()
    item.serial = serial
    item.state = STATE_DRAFT
    item.gesture = built.get("gesture") or ""
    item.view_name = view_name or ""
    item.mark_json = json.dumps(built, separators=(",", ":"))
    item.view_json = json.dumps(view_data or {}, separators=(",", ":"))
    return item


#: Serials flipped to SENT by the most recent send, so a stopped turn can
#: hand them back. Session-only on purpose: a stop and its retry happen in
#: the same session, and a reopened mark is a DRAFT like any other.
_last_sent: list = []


def mark_all_sent(scene):
    """Flip every draft mark to SENT.

    Sent marks stay in the scene rather than being cleared: they are what a
    follow-up turn refers back to, and the vertex groups and cameras they
    name are still live in the .blend.
    """
    _last_sent.clear()
    for item in _collection(scene) or ():
        if item.state == STATE_DRAFT:
            item.state = STATE_SENT
            _last_sent.append(int(item.serial))


def reopen_last_sent(scene) -> int:
    """Hand the last send's marks back as drafts. Returns how many.

    Pressing Stop means "that turn did not happen". The marks that went with
    it were never acted on, so they belong to the NEXT message: a retry
    ("continue", or the same request again) must carry them, or the agent
    builds at the origin exactly as if nothing had been pointed at.
    """
    if not _last_sent:
        return 0
    wanted = set(_last_sent)
    reopened = 0
    for item in _collection(scene) or ():
        if int(item.serial) in wanted and item.state == STATE_SENT:
            item.state = STATE_DRAFT
            reopened += 1
    _last_sent.clear()
    return reopened


def remove_last(scene):
    """Undo the most recent mark, releasing what it created. Returns True."""
    collection = _collection(scene)
    if not collection:
        return False
    index = len(collection) - 1
    _release_item(collection[index], collection)
    collection.remove(index)
    return True


def clear(scene, drafts_only=False):
    """Remove marks and release their cameras and vertex groups."""
    collection = _collection(scene)
    if collection is None:
        return 0

    removed = 0
    for index in range(len(collection) - 1, -1, -1):
        item = collection[index]
        if drafts_only and item.state != STATE_DRAFT:
            continue
        _release_item(item, collection)
        collection.remove(index)
        removed += 1

    if not drafts_only:
        # getattr, not scene.get(): the latter reads custom IDProperties and
        # would always miss the registered RNA property, so the frozen still
        # was never released and got saved into the .blend.
        freeze.release(getattr(scene, "mixar_mark_frame_name", "") or "")
    return removed


def _release_item(item, collection=None):
    """Give back the scene entities one mark owns.

    The baked view camera is SHARED by every mark from the same freeze, so it
    is released only when nothing else still names it. Releasing it
    unconditionally is how undoing one of three marks left the other two
    pointing at a deleted camera — and ``render_viewport(view="mark")`` then
    silently renders the scene camera instead of the frame they describe.

    Best-effort throughout: a mark whose object was deleted between marking
    and undoing must still be removable.
    """
    try:
        data = json.loads(item.mark_json or "{}")
    except ValueError:
        data = {}

    for obj_info in (data.get("resolved") or {}).get("objects") or ():
        group = obj_info.get("vertex_group")
        name = obj_info.get("name")
        if group and name:
            obj = bpy.data.objects.get(name)
            if obj is not None:
                vertex_groups.remove_group(obj, group)

    if item.view_name and not _view_shared(item, collection):
        view_bake.release(item.view_name)


def _view_shared(item, collection):
    """True when another mark still references this mark's baked camera."""
    if collection is None:
        return False
    return any(
        other != item and other.view_name == item.view_name
        for other in collection
    )


# =============================================================================
# Reading
# =============================================================================

def _collection(scene):
    return getattr(scene, "mixar_marks", None)


def has_drafts(scene):
    return any(i.state == STATE_DRAFT for i in _collection(scene) or ())


def count(scene, drafts_only=False):
    collection = _collection(scene) or ()
    if drafts_only:
        return sum(1 for i in collection if i.state == STATE_DRAFT)
    return len(collection)


def _parsed(item):
    try:
        return json.loads(item.mark_json or "{}")
    except ValueError:
        logger.debug("Scribble mark: unreadable record for serial %s", item.serial)
        return None


def build_context(scene, drafts_only=True):
    """The mark payload for a turn, or None when there is nothing to send."""
    collection = _collection(scene) or ()
    marks = []
    views = {}
    for item in collection:
        if drafts_only and item.state != STATE_DRAFT:
            continue
        parsed = _parsed(item)
        if parsed is None:
            continue
        marks.append(parsed)
        if item.view_name and item.view_name not in views:
            try:
                views[item.view_name] = json.loads(item.view_json or "{}")
            except ValueError:
                views[item.view_name] = {}

    if not marks:
        return None
    return payload_mod.build_payload(marks, views, SURFACE_VIEW3D)


def get_marks(include_sent=True):
    """Every mark in the current scene — the agent's re-read entry point.

    Deliberately callable with no arguments from a sandbox script, and
    deliberately returns plain JSON-able data rather than RNA, so a lane can
    read it long after the message that carried it has been compacted away.
    """
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return {"v": MARK_PAYLOAD_VERSION, "surface": SURFACE_VIEW3D,
                "views": {}, "marks": []}

    context = build_context(scene, drafts_only=not include_sent)
    if context is None:
        return {"v": MARK_PAYLOAD_VERSION, "surface": SURFACE_VIEW3D,
                "views": {}, "marks": []}

    # State is useful to the agent — a SENT mark is one it has already been
    # told about, a DRAFT one is new since the last turn.
    states = {i.serial: i.state for i in _collection(scene) or ()}
    for mark in context["marks"]:
        mark["state"] = states.get(mark.get("id"), STATE_SENT)
    return context


def describe(scene, drafts_only=True):
    """Prose restatement of the scene's marks, or an empty string."""
    context = build_context(scene, drafts_only=drafts_only)
    return payload_mod.summarize(context) if context else ""

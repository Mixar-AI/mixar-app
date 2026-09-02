# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Assembling the mark payload — pure, no ``bpy``.

Takes a gesture reading (``gesture.classify``) plus whatever the raycast
resolver managed to establish, and produces the dict that travels to the
agent. Kept free of ``bpy`` so the serialization contract — the part a
backend schema has to agree with — is unit-testable outside Blender.

Two shapes, both versioned:

* a **mark** — one gesture, its 2D region in the frame's normalized
  coordinates, and its client-resolved 3D truth;
* a **payload** — every mark of the turn, plus the ``views`` map they point
  into. Marks made during one freeze share a view; disarming and re-arming
  mints a new one, so a turn can legitimately carry several.

The budget rule: **detail is shed before marks are, and resolution is never
shed at all.** Polygon points are a nicety the agent can live without; which
object the user pointed at is the entire point of the feature.
"""

import json

from .geometry import decimate, normalized_bbox, to_normalized
from ..constants import (
    MARK_JSON_MAX_BYTES,
    MARK_PAYLOAD_VERSION,
    MARK_POLYGON_MAX_POINTS,
    SURFACE_VIEW3D,
    UV_DECIMALS,
)


# =============================================================================
# Building
# =============================================================================

def build_mark(mark_id, view_name, reading, region_width, region_height,
               resolved=None):
    """One mark, ready to serialize.

    Args:
        mark_id: stable serial, unique within the scene.
        view_name: key into the payload's ``views`` map — the baked camera.
        reading: a ``gesture.classify`` result.
        region_width/height: the frozen frame's pixel size.
        resolved: the raycast result, or None when resolution did not run.

    Raises:
        ValueError: on a zero-sized region — every coordinate downstream
            would be silently meaningless, so it fails here instead.
    """
    polygon_px = reading.get("polygon") or []
    anchor_px = reading.get("anchor")

    # A tap has no outline worth sending. Falling back to the anchor keeps
    # the bbox honest (a zero-area point) rather than inventing a region the
    # user never drew.
    bbox_source = polygon_px or ([anchor_px] if anchor_px else [])

    region = {
        "bbox": normalized_bbox(bbox_source, region_width, region_height),
        "polygon": to_normalized(
            decimate(polygon_px, MARK_POLYGON_MAX_POINTS),
            region_width,
            region_height,
        ),
        "anchor": (
            to_normalized([anchor_px], region_width, region_height)[0]
            if anchor_px else None
        ),
        "direction": _rounded_direction(reading.get("direction")),
    }

    mark = {
        "id": int(mark_id),
        "view": view_name,
        "gesture": reading.get("gesture"),
        "closed": bool(reading.get("closed")),
        "region": region,
    }
    if resolved is not None:
        mark["resolved"] = resolved
    return mark


def build_payload(marks, views, surface=SURFACE_VIEW3D):
    """The whole turn's marks plus the views they reference.

    Only views actually referenced by a mark are included — a freeze the user
    armed and then left without drawing on contributes nothing.
    """
    referenced = {m.get("view") for m in marks if m.get("view")}
    return {
        "v": MARK_PAYLOAD_VERSION,
        "surface": surface,
        "views": {name: data for name, data in views.items() if name in referenced},
        "marks": list(marks),
    }


def _rounded_direction(direction):
    if not direction:
        return None
    return [round(float(direction[0]), UV_DECIMALS),
            round(float(direction[1]), UV_DECIMALS)]


# =============================================================================
# Serialization under budget
# =============================================================================

def serialize(payload, max_bytes=MARK_JSON_MAX_BYTES):
    """``(json_text, notes)`` — compact JSON, shrunk to fit *max_bytes*.

    Marks ride inside the model's context window every turn, so this is a
    prompt budget rather than a transport limit. Shedding happens in a fixed
    order, cheapest meaning first:

    1. thin every polygon to 8 points,
    2. drop polygons entirely, leaving each mark's bbox,
    3. drop the OLDEST marks, newest-last being the ones most likely still
       being talked about.

    ``resolved`` is never touched. It is the measured answer to "what did the
    user point at", and a payload that fits but no longer says that has
    thrown away the only thing the agent could not have worked out itself.

    *notes* lists what was shed, so the caller can say so rather than
    silently sending less than the user drew.
    """
    notes = []
    text = _dump(payload)
    if len(text.encode("utf-8")) <= max_bytes:
        return text, notes

    working = json.loads(text)

    for mark in working["marks"]:
        polygon = mark.get("region", {}).get("polygon") or []
        if len(polygon) > 8:
            mark["region"]["polygon"] = decimate(polygon, 8)
    text = _dump(working)
    if len(text.encode("utf-8")) <= max_bytes:
        notes.append("mark outlines thinned to fit the context budget")
        return text, notes

    for mark in working["marks"]:
        mark.get("region", {})["polygon"] = []
    text = _dump(working)
    if len(text.encode("utf-8")) <= max_bytes:
        notes.append("mark outlines dropped to fit the context budget; "
                     "bounding boxes and resolved objects kept")
        return text, notes

    dropped = 0
    while len(working["marks"]) > 1:
        working["marks"].pop(0)
        dropped += 1
        working["views"] = _used_views(working)
        text = _dump(working)
        if len(text.encode("utf-8")) <= max_bytes:
            notes.append(f"{dropped} oldest mark(s) dropped to fit the "
                         f"context budget")
            return text, notes

    if dropped:
        notes.append(f"{dropped} oldest mark(s) dropped to fit the context "
                     f"budget")
    notes.append("payload still over budget after shedding; sent as-is")
    return _dump(working), notes


def _dump(payload):
    return json.dumps(payload, separators=(",", ":"), sort_keys=False)


def _used_views(payload):
    referenced = {m.get("view") for m in payload.get("marks", [])}
    return {k: v for k, v in payload.get("views", {}).items() if k in referenced}


# =============================================================================
# Prose
# =============================================================================

def summarize(payload):
    """A human-readable restatement of what the user pointed at.

    Models act on sentences far more reliably than on JSON buried in a
    context window, so the marks are stated twice: once as data the agent can
    index into, and once as prose it will actually read. This is the prose.
    """
    marks = payload.get("marks") or []
    if not marks:
        return ""

    lines = []
    for mark in marks:
        lines.append(_summarize_mark(mark, len(marks) > 1))
    return "\n".join(lines)


def _summarize_mark(mark, numbered):
    prefix = f"Mark {mark.get('id')}: " if numbered else ""
    gesture = mark.get("gesture") or "mark"
    resolved = mark.get("resolved") or {}

    verb = {
        "circle": "circled",
        "arrow": "drew an arrow at",
        "point": "tapped",
        "strike": "struck through",
        "stroke": "marked",
    }.get(gesture, "marked")

    if not resolved:
        return f"{prefix}the user {verb} a region of the frozen view."

    if not resolved.get("hit"):
        point = resolved.get("point")
        if resolved.get("plane") and point:
            coords = ", ".join(f"{c:g}" for c in point)
            return (f"{prefix}the user {verb} an empty spot on the ground "
                    f"plane at world ({coords}) — a placement target.")
        reason = resolved.get("empty_reason") or "nothing under it"
        return (f"{prefix}the user {verb} empty space "
                f"({reason}) — no object is under this mark.")

    objects = resolved.get("objects") or []
    if not objects:
        return f"{prefix}the user {verb} a region, but no object resolved."

    first = objects[0]
    name = first.get("name")

    # object_fraction, NOT coverage. coverage says how much of the MARK is
    # this object; object_fraction says how much of the OBJECT the mark took.
    # "covering about 72% of it" is a claim about the object, so it has to
    # read the second one or the agent acts on the wrong number.
    fraction = first.get("object_fraction")
    if not first.get("partial"):
        part = ", covering essentially all of it"
    elif fraction is not None:
        part = f", covering about {int(round(float(fraction) * 100))}% of it"
    else:
        part = ", covering part of it"

    sentence = f"{prefix}the user {verb} `{name}`{part}."

    if first.get("vertex_group"):
        sentence += (f" The marked faces are in the vertex group "
                     f"`{first['vertex_group']}` on `{name}` — select that "
                     f"rather than re-deriving the region.")

    others = [o.get("name") for o in objects[1:] if o.get("name")]
    if others:
        sentence += f" Also partly covered: {', '.join(f'`{o}`' for o in others)}."

    point = resolved.get("point")
    if point:
        coords = ", ".join(f"{c:g}" for c in point)
        sentence += f" Surface point at world ({coords})."

    direction = (mark.get("region") or {}).get("direction")
    if direction and gesture == "arrow":
        sentence += (f" The arrow points ({direction[0]:g}, {direction[1]:g}) "
                     f"in the frame — right/up positive.")

    return sentence

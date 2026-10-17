# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pair each encoded chat image with its ``bpy.data.images`` name.

The backend labels every image block with the name the agent passes to
generation tools. Names and images used to travel as two independently
compacted lists, so one skipped image (timeout, encode failure, a video, a
model file) or one unresolved name shifted every later label onto the wrong
image. Here a name rides only with the image it was resolved for: a dropped
image drops its name, and an encoded image without a name carries none.

bpy-free by design (unit-tested outside Blender).
"""


def pair_names_with_images(encoded, names) -> list:
    """Encoded image dicts for the wire, each carrying its own name.

    ``encoded`` and ``names`` are index-aligned with the outgoing attachment
    list: ``encoded[i]`` is ``(base64, mime_type)`` or ``None`` when that
    attachment produced no image; ``names[i]`` is its resolved name or ``""``.
    Returns ``[{"base64", "mime_type"[, "name"]}]`` in attachment order;
    ``"name"`` is present only when non-empty.
    """
    names = list(names or ())
    paired = []
    for index, item in enumerate(encoded or ()):
        if not item:
            continue  # the name (if any) goes with the dropped image
        b64, mime_type = item
        entry = {"base64": b64, "mime_type": mime_type}
        name = names[index] if index < len(names) else ""
        if name:
            entry["name"] = str(name)
        paired.append(entry)
    return paired


def legacy_attachment_names(images) -> list:
    """The legacy positional ``attachment_names``: the names of the encoded
    images that have one, in order (older backends read only this list)."""
    return [img["name"] for img in images or () if img.get("name")]

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Generic PropertyGroup <-> dict serialization for chat messages.

Extracted from ``ui/operators/export_ops.py`` so the same deep
snapshot/restore machinery can be shared by:

  * the "Export .blend without chat history" operator (strip + restore),
  * the local chat-history archive (``core/chat_history.py``), which
    persists whole sessions as JSON under ``~/.mixar/chat_history/``.

Everything here is deliberately bpy-free at import time: the functions
only touch the PropertyGroup instances passed in, so the module can be
imported in isolated tests.
"""


def is_collection_property(item) -> bool:
    """True if ``item`` is a bpy_prop_collection wrapper (CollectionProperty).

    These can't be deep-copied via ``getattr`` because Blender returns a
    live reference into the parent struct. ``coll.clear()`` on the parent
    invalidates these references — meaning a naive snapshot becomes a
    list of pointers to freed memory.
    """
    # Avoid importing bpy at module-load — only available inside Blender.
    return type(item).__name__ in ("bpy_prop_collection", "bpy_prop_collection_idprop")


def snapshot_propgroup(pg) -> dict:
    """Recursively materialise a PropertyGroup into nested Python dicts.

    Each leaf is a scalar copy (str/int/float/bool). Nested
    CollectionProperty fields become lists of dicts. The result is
    safe to persist across a ``coll.clear()`` on the owning collection
    because nothing in the returned structure holds a Blender pointer.
    """
    out = {}
    for prop_name in pg.bl_rna.properties.keys():
        if prop_name == "rna_type":
            continue
        try:
            value = getattr(pg, prop_name)
        except Exception:
            continue
        if is_collection_property(value):
            out[prop_name] = [snapshot_propgroup(item) for item in value]
        else:
            out[prop_name] = value
    return out


def restore_propgroup(pg, data: dict) -> None:
    """Inverse of ``snapshot_propgroup`` — populate ``pg`` from a data dict.

    Nested CollectionProperties get cleared, then rebuilt entry-by-entry
    via ``coll.add()`` followed by a recursive restore. Scalar leaves
    are set via ``setattr``; set failures (read-only, schema-changed,
    type-mismatched) are skipped quietly so a partial restore still
    yields a usable in-memory state.
    """
    for prop_name, value in data.items():
        if isinstance(value, list):
            # Nested collection — clear and rebuild.
            try:
                sub_coll = getattr(pg, prop_name)
            except Exception:
                continue
            if not is_collection_property(sub_coll):
                continue
            sub_coll.clear()
            for entry in value:
                new_item = sub_coll.add()
                if isinstance(entry, dict):
                    restore_propgroup(new_item, entry)
        else:
            try:
                setattr(pg, prop_name, value)
            except Exception:
                # Read-only properties (e.g. computed), schema mismatch,
                # or wrong-type fields. Skip rather than tank the
                # restore on one bad leaf.
                pass

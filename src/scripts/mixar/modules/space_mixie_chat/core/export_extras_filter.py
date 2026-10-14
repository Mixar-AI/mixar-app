# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Strip Mixar's registered properties from glTF ``extras`` (privacy).

``export_extras=True`` (the ``web`` preset) writes every ID property as glTF
extras, and ``bpy.props``-registered properties are stored as ID
properties: a scene with chat history would ship its draft, transcript,
session id, moodboard and Director state. After the write, every ``extras``
key that is a REGISTERED RNA property of the matching Blender type is
dropped; user custom properties (never in ``bl_rna.properties``) survive.
Belt and braces: ``mixie_*`` / ``mixar_*`` (and ``_``-prefixed) (except ``mixar_active_camera``,
the viewer's home-camera tag) and ``_RNA_UI`` keys go too. A GLB is
rewritten in place with its BIN chunk untouched; a ``.gltf`` JSON likewise.
"""

from __future__ import annotations

import json
import struct

JSON_CHUNK = 0x4E4F534A
KEEP = frozenset({"mixar_active_camera"})
PREFIXES = ("mixie_", "mixar_", "_mixie_", "_mixar_", "_RNA_UI")
# glTF collection → Blender RNA type whose registered properties it may carry.
SECTIONS = {"scenes": "Scene", "nodes": "Object", "meshes": "Mesh",
            "materials": "Material", "cameras": "Camera"}
LIGHT_TYPE = "Light"


def registered_properties() -> dict:
    """``{rna type: {identifier, ...}}`` from the live ``bpy.types``."""
    out = {}
    try:
        import bpy

        for name in set(SECTIONS.values()) | {LIGHT_TYPE}:
            rna = getattr(bpy.types, name).bl_rna
            out[name] = {str(p.identifier) for p in rna.properties}
    except Exception:  # noqa: BLE001 — the prefix rule still applies
        pass
    return out


def _private(key: str, registered: set) -> bool:
    if key in KEEP:
        return False
    return key in registered or key.startswith(PREFIXES)


def _clean(items, registered: set) -> int:
    stripped = 0
    for item in items or ():
        extras = item.get("extras") if isinstance(item, dict) else None
        if not isinstance(extras, dict):
            continue
        for key in [k for k in extras if _private(str(k), registered)]:
            del extras[key]
            stripped += 1
        if not extras:
            del item["extras"]
    return stripped


def strip_document(doc: dict, registered: dict | None = None) -> int:
    """Strip private extras from a glTF JSON document in place; returns the
    number of keys removed."""
    registered = registered if registered is not None else registered_properties()
    stripped = 0
    for section, rna in SECTIONS.items():
        stripped += _clean(doc.get(section), registered.get(rna, set()))
    lights = ((doc.get("extensions") or {}).get("KHR_lights_punctual") or {}).get("lights")
    stripped += _clean(lights, registered.get(LIGHT_TYPE, set()))
    return stripped


def _rewrite_glb(path: str, registered) -> int:
    with open(path, "rb") as handle:
        data = handle.read()
    magic, version, _length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError("not a GLB container")
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != JSON_CHUNK:
        raise ValueError("first GLB chunk is not JSON")
    doc = json.loads(data[20:20 + chunk_length].decode("utf-8"))
    stripped = strip_document(doc, registered)
    if not stripped:
        return 0
    payload = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload += b" " * (-len(payload) % 4)  # spec: JSON chunk padded with spaces
    rest = data[20 + chunk_length:]  # BIN chunk (and any others), byte-identical
    body = struct.pack("<II", len(payload), JSON_CHUNK) + payload + rest
    with open(path, "wb") as handle:
        handle.write(struct.pack("<4sII", b"glTF", version, 12 + len(body)) + body)
    return stripped


def _rewrite_gltf(path: str, registered) -> int:
    with open(path, "r", encoding="utf-8") as handle:
        doc = json.load(handle)
    stripped = strip_document(doc, registered)
    if stripped:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
    return stripped


def strip_private_extras(path: str, fmt: str, registered: dict | None = None) -> int:
    """Rewrite the written glTF/GLB at ``path`` without private extras."""
    registered = registered if registered is not None else registered_properties()
    fmt = str(fmt or "").lower().lstrip(".")
    if fmt == "glb":
        return _rewrite_glb(path, registered)
    if fmt == "gltf":
        return _rewrite_gltf(path, registered)
    return 0

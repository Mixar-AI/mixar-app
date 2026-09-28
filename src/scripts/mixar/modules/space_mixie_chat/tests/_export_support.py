# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared helper for the export tests: build a tiny, valid GLB on disk."""

import json
import struct


def glb_bytes(*, meshes=1, animations=(), materials=("Mat",), images=1, embedded=True,
              draco=False, bin_size=2048, size=(2.0, 1.0, 0.5), node_translations=None,
              scenes=1, extra_nodes=()) -> bytes:
    """A minimal glTF 2.0 binary: ``meshes`` cube-like primitives sharing one
    POSITION accessor (min/max spanning ``size``) and one index accessor."""
    accessors = [
        {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3",
         "min": [0.0, 0.0, 0.0], "max": list(size)},
        {"bufferView": 0, "componentType": 5123, "count": 36, "type": "SCALAR"},
    ]
    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": bin_size}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": bin_size}],
        "accessors": accessors,
        "meshes": [{"name": f"Mesh{i}", "primitives": [
            {"attributes": {"POSITION": 0}, "indices": 1, "material": 0 if materials else None}
        ]} for i in range(meshes)],
        "nodes": [{"mesh": i, "name": f"Node{i}",
                   **({"translation": list(node_translations[i])} if node_translations else {})}
                  for i in range(meshes)] + list(extra_nodes),
        "scenes": [{"nodes": list(range(meshes))}] + [{"nodes": []} for _ in range(scenes - 1)],
        "materials": [{"name": name} for name in materials],
        "images": [
            {"bufferView": 0, "mimeType": "image/png"} if embedded else {"uri": f"tex{i}.png"}
            for i in range(images)
        ],
        "animations": [{"name": name, "channels": [], "samplers": []} for name in animations],
    }
    if draco:
        doc["extensionsUsed"] = ["KHR_draco_mesh_compression"]
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            if prim["material"] is None:
                del prim["material"]
    payload = json.dumps(doc).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    blob = b"\0" * bin_size
    body = (struct.pack("<II", len(payload), 0x4E4F534A) + payload
            + struct.pack("<II", len(blob), 0x004E4942) + blob)
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def write_glb(path, **kwargs) -> str:
    with open(path, "wb") as handle:
        handle.write(glb_bytes(**kwargs))
    return path

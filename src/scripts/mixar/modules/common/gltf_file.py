# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit glTF metadata while keeping GLB binary chunks off the Python heap."""

import json
import os
import shutil
import struct
import uuid

_HEADER = struct.Struct("<4sIII4s")  # container header and first chunk header


def rewrite_document(path, edit, *, fmt=None, ensure_ascii=True, indent=None):
    """Apply edit(doc). Its truthy return value requests atomic replacement."""
    temp = None
    try:
        with open(path, "rb") as source:
            if fmt is None:
                fmt = "glb" if source.read(4) == b"glTF" else "gltf"
                source.seek(0)
            if fmt == "glb":
                header = source.read(_HEADER.size)
                if len(header) != _HEADER.size:
                    raise ValueError("Incomplete GLB header")
                magic, version, _, size, kind = _HEADER.unpack(header)
                if magic != b"glTF" or kind != b"JSON":
                    raise ValueError("Expected a GLB with a leading JSON chunk")
                tail_size = os.fstat(source.fileno()).st_size - _HEADER.size - size
                if tail_size < 0:
                    raise ValueError("Incomplete GLB JSON chunk")
                doc = json.loads(source.read(size).decode("utf-8"))
            else:
                doc = json.loads(source.read().decode("utf-8"))
            changed = edit(doc)
            if not changed:
                return changed

            sibling = f"{path}.tmp-{uuid.uuid4().hex}"
            with open(sibling, "xb") as target:
                temp = sibling
                if fmt == "glb":
                    payload = json.dumps(doc, separators=(",", ":"), ensure_ascii=ensure_ascii).encode()
                    payload += b" " * (-len(payload) % 4)
                    total = _HEADER.size + len(payload) + tail_size
                    target.write(_HEADER.pack(magic, version, total, len(payload), kind))
                    target.write(payload)
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                else:
                    target.write(json.dumps(doc, ensure_ascii=ensure_ascii, indent=indent).encode())
        # Windows requires both file handles to be closed before replacement.
        os.replace(temp, path)
        temp = None
        return changed
    finally:
        if temp is not None:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass

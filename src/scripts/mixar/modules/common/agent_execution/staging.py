# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Worker-side staging: write a task's objects as a native artifact.

Called from a TRUSTED backend script template that runs inside the
background worker's sandboxed executor (``mixar.*`` imports are allowed
there). The staging directory comes from the launch environment the parent
wrote (``MIXAR_SANDBOX_STAGING_DIR``); the returned manifest is path-free.
"""

from __future__ import annotations

import hashlib
import math
import os
import uuid
from typing import Iterable

from .artifacts import is_artifact_id

STAGING_ENV = "MIXAR_SANDBOX_STAGING_DIR"


def staging_root() -> str:
    root = os.environ.get(STAGING_ENV, "")
    if not root or not os.path.isdir(root):
        raise RuntimeError("worker has no staging directory (MIXAR_SANDBOX_STAGING_DIR)")
    return root


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _bbox(objects) -> tuple[list, list, bool]:
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    finite = True
    for ob in objects:
        try:
            mw = ob.matrix_world
            for corner in ob.bound_box:
                p = mw @ type(mw.translation)(corner) if hasattr(mw, "translation") else corner
                for i in range(3):
                    v = float(p[i])
                    if not math.isfinite(v):
                        finite = False
                        continue
                    lo[i] = min(lo[i], v)
                    hi[i] = max(hi[i], v)
        except Exception:
            continue
    if any(math.isinf(v) for v in lo + hi):
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], finite and False
    return lo, hi, finite


def stage_collection(artifact_id: str, collection_name: str, object_names: Iterable[str]) -> dict:
    """Move ``object_names`` into ``collection_name`` and write the artifact."""
    import bpy

    if not is_artifact_id(artifact_id):
        artifact_id = str(uuid.uuid4())
    if not collection_name or "/" in collection_name or "\\" in collection_name:
        raise ValueError("collection_name must be a plain datablock name")
    root = staging_root()

    coll = bpy.data.collections.get(collection_name) or bpy.data.collections.new(collection_name)
    objects = []
    missing = []
    for name in object_names:
        ob = bpy.data.objects.get(name)
        if ob is None:
            missing.append(name)
            continue
        for user in list(ob.users_collection):
            if user is not coll:
                try:
                    user.objects.unlink(ob)
                except Exception:
                    pass
        if ob.name not in coll.objects:
            coll.objects.link(ob)
        objects.append(ob)
    try:
        bpy.ops.file.pack_all()
    except Exception:
        pass

    path = os.path.join(root, f"{artifact_id}.blend")
    bpy.data.libraries.write(path, {coll}, fake_user=True)
    lo, hi, finite = _bbox(objects)
    return {
        "artifact_id": artifact_id,
        "collection_name": coll.name,
        "object_names": [o.name for o in objects],
        "missing_objects": missing,
        "content_hash": _sha256(path),
        "size_bytes": os.path.getsize(path),
        "object_count": len(objects),
        "bbox_min": lo,
        "bbox_max": hi,
        "finite": bool(finite and objects),
    }


def reset_worker_scene() -> dict:
    """Return the worker to an empty document so it can be reused."""
    import bpy

    try:
        bpy.ops.wm.read_homefile(use_empty=True)
        return {"success": True, "method": "read_homefile"}
    except Exception:
        pass
    removed = 0
    for collection_name in ("objects", "meshes", "materials", "images", "collections"):
        data = getattr(bpy.data, collection_name)
        for block in list(data):
            try:
                data.remove(block)
                removed += 1
            except Exception:
                pass
    return {"success": True, "method": "manual", "removed": removed}

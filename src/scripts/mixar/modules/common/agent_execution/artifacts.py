# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Native artifact registry on the parent (foreground) side.

Workers write ``<staging_dir>/<artifact_id>.blend``; the backend only ever
holds the id plus a content hash. ``resolve`` is the ONE place an id becomes
a path, and it is called only by trusted client code (the commit handler) —
never by a model script and never with a value that could be a path.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from typing import Optional

from .paths import staging_dir

MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class ArtifactError(Exception):
    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type


def is_artifact_id(value) -> bool:
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def artifact_path(instance_id: str, artifact_id: str) -> str:
    if not is_artifact_id(artifact_id):
        raise ArtifactError("artifact_missing", "artifact id is not a bare uuid")
    return os.path.join(staging_dir(instance_id, create=False), f"{artifact_id}.blend")


def resolve(instance_id: str, artifact_id: str, expected_hash: Optional[str] = None,
            max_bytes: int = MAX_ARTIFACT_BYTES) -> str:
    """Validated local path for an artifact. Raises ArtifactError."""
    path = artifact_path(instance_id, artifact_id)
    if not os.path.isfile(path):
        raise ArtifactError("artifact_missing", f"artifact {artifact_id} not found")
    size = os.path.getsize(path)
    if size > max_bytes:
        raise ArtifactError("artifact_missing", f"artifact {artifact_id} exceeds size cap ({size} bytes)")
    if expected_hash:
        actual = sha256_file(path)
        if actual != expected_hash:
            raise ArtifactError("hash_mismatch", f"artifact {artifact_id} content hash mismatch")
    return path


def list_artifacts(instance_id: str) -> list[dict]:
    root = staging_dir(instance_id, create=False)
    if not os.path.isdir(root):
        return []
    out = []
    for name in os.listdir(root):
        if not name.endswith(".blend"):
            continue
        aid = name[:-6]
        if not is_artifact_id(aid):
            continue
        full = os.path.join(root, name)
        try:
            st = os.stat(full)
        except OSError:
            continue
        out.append({"artifact_id": aid, "size_bytes": st.st_size, "mtime": st.st_mtime})
    return sorted(out, key=lambda a: a["mtime"])


def cleanup(instance_id: str, keep_ids: set[str] | None = None, max_age_s: float = 7 * 86400) -> int:
    """Remove artifacts older than ``max_age_s`` unless referenced in ``keep_ids``."""
    keep = set(keep_ids or ())
    now = time.time()
    removed = 0
    for art in list_artifacts(instance_id):
        if art["artifact_id"] in keep or now - art["mtime"] < max_age_s:
            continue
        try:
            os.remove(artifact_path(instance_id, art["artifact_id"]))
            removed += 1
        except OSError:
            pass
    return removed

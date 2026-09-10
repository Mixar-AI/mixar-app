# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Client-local storage locations for the v3 execution protocol.

Everything here is a LOCAL path: the journal, the artifact staging area.
None of these values are ever sent upstream — the backend addresses
artifacts by opaque ids only. ``MIXAR_AGENT_CACHE_DIR`` overrides the root
(tests, portable installs).
"""

from __future__ import annotations

import os
import re
import tempfile

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def cache_root() -> str:
    """Per-user Mixar data directory (created)."""
    override = os.environ.get("MIXAR_AGENT_CACHE_DIR")
    if override:
        os.makedirs(override, exist_ok=True)
        return override
    try:
        import bpy

        path = bpy.utils.user_resource("DATAFILES", path="mixar", create=True)
        if isinstance(path, str) and path:
            os.makedirs(path, exist_ok=True)
            return path
    except Exception:
        pass
    path = os.path.join(tempfile.gettempdir(), "mixar")
    os.makedirs(path, exist_ok=True)
    return path


def safe_id(value: str, what: str = "id") -> str:
    """Refuse anything that could be a path segment trick."""
    if not isinstance(value, str) or not _SAFE_ID.match(value):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


def staging_dir(instance_id: str, create: bool = True) -> str:
    """Artifact staging directory for one foreground instance's workers."""
    path = os.path.join(cache_root(), "agent_artifacts", safe_id(instance_id, "instance id"))
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def journal_path() -> str:
    return os.path.join(cache_root(), "agent_journal.sqlite")

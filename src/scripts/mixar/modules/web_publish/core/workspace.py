# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Temporary publish workspace (GLB + thumbnail). No bpy: the worker thread
owns cleanup."""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Tuple

from mixar.modules.web_publish.constants import (
    GLB_EXPORT_FILENAME,
    THUMBNAIL_FILENAME,
    WORKSPACE_PREFIX,
)


def make_export_workspace() -> Tuple[str, str]:
    """``(workspace, glb_path)`` in a fresh temp directory. Caller cleans up."""
    workspace = tempfile.mkdtemp(prefix=WORKSPACE_PREFIX)
    return workspace, os.path.join(workspace, GLB_EXPORT_FILENAME)


def thumbnail_path(workspace: str) -> str:
    return os.path.join(workspace, THUMBNAIL_FILENAME)


def cleanup_workspace(workspace: str) -> None:
    """Remove a workspace made by ``make_export_workspace`` (best-effort)."""
    if not workspace or not os.path.basename(workspace).startswith(WORKSPACE_PREFIX):
        return
    shutil.rmtree(workspace, ignore_errors=True)

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local-models storage locations.

Follows the generation-catalog storage pattern: the base directory is
resolved through ``bpy.utils`` exactly once, on Blender's main thread, at
register time (``initialize()``), and cached in a module global so that
background download/supervisor threads never touch ``bpy``.

``bpy`` is imported lazily and guarded, so the standalone test suite (where
``bpy`` is a MagicMock) can simply monkeypatch :data:`_resolved_base` (or
call :func:`set_base_dir`) to point at a temp directory.
"""

import os
import threading
from typing import Optional

from mixar.config.logging_config import get_logger

from ..constants import DATAFILES_SUBDIR, MANIFEST_FILENAME

logger = get_logger(__name__)

_resolved_base: Optional[str] = None
_lock = threading.Lock()


def _default_base() -> str:
    """Resolve the storage base. Main thread only (touches bpy.utils)."""
    try:
        import bpy

        path = bpy.utils.user_resource(
            "DATAFILES", path=DATAFILES_SUBDIR, create=True
        )
        # Guarded with isinstance: in the standalone suite bpy is a
        # MagicMock and user_resource returns a truthy mock, not a str.
        if isinstance(path, str) and path:
            return path
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), ".mixar", "local_models")


def initialize() -> str:
    """Resolve and cache the base directory. Call on the main thread.

    Idempotent. Every other helper in this module reads the cached value,
    so once this has run at register time, all accessors are safe from any
    thread.
    """
    global _resolved_base
    with _lock:
        if _resolved_base is None:
            _resolved_base = _default_base()
            logger.debug("Local models base dir: %s", _resolved_base)
        return _resolved_base


def set_base_dir(path: str) -> None:
    """Override the base directory (tests / tooling)."""
    global _resolved_base
    with _lock:
        _resolved_base = path


def base_dir() -> str:
    """The cached base directory (resolving it on first use if needed)."""
    if _resolved_base is not None:
        return _resolved_base
    return initialize()


def runtime_dir(tag: str, variant: str) -> str:
    """Install directory for one runtime build (not created here)."""
    return os.path.join(base_dir(), "runtimes", tag, variant)


def models_dir() -> str:
    """Root directory for downloaded model files (not created here)."""
    return os.path.join(base_dir(), "models")


def model_dir(model_id: str) -> str:
    """Per-model directory (mmproj filenames collide across repos)."""
    return os.path.join(models_dir(), model_id)


def manifest_path() -> str:
    return os.path.join(base_dir(), MANIFEST_FILENAME)

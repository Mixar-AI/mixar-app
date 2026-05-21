# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Save/load handlers for Mixar file versioning.

Stamps the current Python schema version on save, and runs pending
migrations on load.
"""

import logging

import bpy
from bpy.app.handlers import persistent

from .registry import MIXAR_PY_VERSION, get_file_version, set_file_version, run_migrations

logger = logging.getLogger(__name__)


@persistent
def _on_save_pre(*_args):
    """Stamp current Mixar Python version on every scene before saving."""
    for scene in bpy.data.scenes:
        set_file_version(scene)


@persistent
def _on_load_post(*_args):
    """Run pending migrations after loading a file."""
    forward_compat_warned = False
    for scene in bpy.data.scenes:
        file_ver = get_file_version(scene)
        if file_ver > MIXAR_PY_VERSION:
            if not forward_compat_warned:
                logger.warning(
                    "File was saved by newer Mixar (Python version %s > %s)",
                    file_ver, MIXAR_PY_VERSION,
                )
                forward_compat_warned = True
        elif file_ver < MIXAR_PY_VERSION:
            run_migrations(scene)


def register():
    """Register save/load handlers."""
    bpy.app.handlers.save_pre.append(_on_save_pre)
    bpy.app.handlers.load_post.append(_on_load_post)
    logger.info("Versioning handlers registered")


def unregister():
    """Remove save/load handlers."""
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if _on_save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_on_save_pre)
    logger.info("Versioning handlers unregistered")

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Platform-Specific Installer Launcher

Launches the downloaded installer as a detached process, then
(optionally) quits Blender so the installer can replace binaries.
"""

import os
import subprocess
import sys
import tempfile

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.platform_utils import is_linux, is_macos, is_windows

from ..constants import UPDATES_CACHE_DIR

logger = get_logger(__name__)


def _is_inside_cache(filepath: str) -> bool:
    """Refuse to launch any installer that isn't inside our update cache dir.

    Defence-in-depth against a malformed download path escaping the cache
    (e.g. a future bug that lets a server-supplied field control the path).
    """
    cache = os.path.realpath(os.path.join(tempfile.gettempdir(), UPDATES_CACHE_DIR))
    real = os.path.realpath(filepath)
    try:
        return os.path.commonpath([real, cache]) == cache
    except ValueError:
        return False


def launch_installer(filepath: str, quit_blender: bool = True) -> bool:
    """Launch *filepath* with the platform's default handler.

    Args:
        filepath: Absolute path to the installer binary.
        quit_blender: Whether to quit Blender after launching.

    Returns:
        True if the process was started successfully.
    """
    if not _is_inside_cache(filepath):
        logger.error("Refusing to launch installer outside cache dir: %s", filepath)
        return False
    try:
        if is_windows():
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                [filepath],
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        elif is_macos():
            subprocess.Popen(
                ["open", filepath],
                start_new_session=True,
                close_fds=True,
            )
        elif is_linux():
            subprocess.Popen(
                ["xdg-open", filepath],
                start_new_session=True,
                close_fds=True,
            )
        else:
            logger.error("Unsupported platform: %s", sys.platform)
            return False

        logger.info("Installer launched: %s", filepath)

        if quit_blender:
            _quit_blender()

        return True

    except Exception as e:
        logger.error("Failed to launch installer: %s", e)
        return False


def _quit_blender() -> None:
    """Ask Blender to quit gracefully."""
    try:
        import bpy

        bpy.ops.wm.quit_blender()
    except Exception as e:
        logger.warning("Failed to quit Blender: %s", e)

# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Bootstrap Module.

Adds an explicit teardown path for moodboard-owned resources so that
addon disable / Blender exit reliably releases:

  * Per-scene loaded image datablocks (image, display_image,
    compressed_image, mask_image) — these are packed at load time, so
    leaving them attached holds full RGBA bytes for the rest of the
    session.
  * Background managers' in-flight state (scene_gen, scene_segment,
    scene_gen_exp) — their long-lived dicts pin GLB /
    image / mask payloads that can run to tens of MB per job.
"""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _release_all_scenes_images() -> int:
    """Release moodboard images on every scene in the current file."""
    from mixar.modules.moodboard.core.image_lifecycle import (
        release_all_moodboard_images,
    )
    total = 0
    try:
        for scene in bpy.data.scenes:
            total += release_all_moodboard_images(scene)
            coll = getattr(scene, "mixie_moodboard_images", None)
            if coll is not None:
                coll.clear()
    except (AttributeError, ReferenceError):
        # bpy.data may be unavailable during full interpreter shutdown.
        pass
    return total


def _clear_all_managers() -> None:
    """Stop polling/threads and drop captured state in moodboard managers."""
    try:
        from mixar.modules.moodboard.core.scene_segment_manager import (
            get_scene_segment_manager,
        )
        get_scene_segment_manager().clear_all()
    except Exception as exc:
        logger.debug("scene_segment_manager.clear_all failed: %s", exc)

    try:
        from mixar.modules.moodboard.core.scene_gen_manager import (
            get_scene_gen_manager,
        )
        get_scene_gen_manager().clear_all()
    except Exception as exc:
        logger.debug("scene_gen_manager.clear_all failed: %s", exc)

    try:
        from mixar.modules.moodboard.core.scene_gen_exp_manager import (
            get_scene_gen_exp_manager,
        )
        get_scene_gen_exp_manager().clear_all()
    except Exception as exc:
        logger.debug("scene_gen_exp_manager.clear_all failed: %s", exc)


def register() -> None:
    """Start the moodboard-selection → chat-attachment sync poll."""
    try:
        from mixar.modules.moodboard.core import chat_sync
        chat_sync.register()
    except Exception as exc:
        logger.warning("Moodboard chat_sync register failed: %s", exc)


def unregister() -> None:
    """Drain moodboard managers and release every moodboard image datablock."""
    try:
        from mixar.modules.moodboard.core import chat_sync
        chat_sync.unregister()
    except Exception as exc:
        logger.debug("Moodboard chat_sync unregister error: %s", exc)

    try:
        _clear_all_managers()
    except Exception as exc:
        logger.debug("Moodboard manager teardown error: %s", exc)

    try:
        freed = _release_all_scenes_images()
        if freed:
            logger.debug("Moodboard teardown released %d image entries", freed)
    except Exception as exc:
        logger.debug("Moodboard image teardown error: %s", exc)

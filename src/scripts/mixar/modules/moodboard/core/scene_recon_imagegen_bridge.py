# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bridge: ImageGenJob subclass that chains into scene reconstruction.

When scene reconstruction is triggered from a text prompt (no image),
we first generate an image via the imagegen queue, then chain straight
into the scene-recon queue once the image is ready.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue import get_queue
from mixar.modules.common.job_queue.constants import FEATURE_IMAGEGEN
from mixar.modules.common.job_queue.core.job import JobState, TERMINAL_STATES
from mixar.modules.moodboard.core.imagegen_queue import ImageGenJob

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom Job
# ---------------------------------------------------------------------------


@dataclass
class _SceneReconImageGenJob(ImageGenJob):
    """ImageGenJob that chains scene reconstruction after image download."""

    _stored_prompt: str = ""
    _recon_params: dict = field(default_factory=dict)
    _sidebar_available: bool = True

    def handle_result(self, result_files, on_done, on_error):
        """Download image, add to moodboard, then submit scene recon."""
        if not self._image_urls:
            on_error("No image URLs in server response")
            return True

        urls = list(self._image_urls)
        prompt = self._stored_prompt or self.prompt
        recon = dict(self._recon_params)
        sidebar_avail = self._sidebar_available

        def _bg_download():
            try:
                from mixar.modules.common.utils.image_utils import (
                    add_image_to_moodboard,
                    compress_image_for_upload,
                    load_image_from_url,
                )

                timestamp = int(time.time())
                img = load_image_from_url(urls[0], f"scene_recon_{timestamp}")

                def _chain():
                    try:
                        add_image_to_moodboard(img, prompt)
                        logger.info(
                            "Generated image added to moodboard: %s", img.name,
                        )
                        image_bytes = compress_image_for_upload(img)

                        scene = bpy.context.scene
                        sidebar_tab = None
                        if sidebar_avail and hasattr(scene, "mixie_moodboard_sidebar"):
                            sidebar = scene.mixie_moodboard_sidebar
                            if hasattr(sidebar, "tab_scene_recon"):
                                sidebar_tab = sidebar.tab_scene_recon
                                sidebar_tab.stage_name = "Starting reconstruction..."
                                sidebar_tab.stage_detail = ""

                        from mixar.modules.moodboard.core.scene_recon_submission import (
                            submit_recon_job,
                        )

                        submit_recon_job(
                            scene, sidebar_tab, image_bytes, **recon,
                        )
                        on_done(img.name)
                    except Exception as e:
                        logger.error("Error chaining scene recon: %s", e)
                        on_error(f"Error: {e}")
                    return None

                bpy.app.timers.register(_chain, first_interval=0.0)
            except Exception as e:
                err = f"Failed to download generated image: {e}"
                logger.error("[SceneRecon] %s", err)

                def _fail():
                    on_error(err)
                    return None

                bpy.app.timers.register(_fail, first_interval=0.0)

        threading.Thread(target=_bg_download, daemon=True).start()
        return True


# ---------------------------------------------------------------------------
# Enqueue helper
# ---------------------------------------------------------------------------


def enqueue_imagegen_for_recon(
    *,
    prompt: str,
    stored_prompt: str = "",
    recon_params: dict,
    sidebar_available: bool = True,
    on_error: Optional[Callable[[str], None]] = None,
) -> Optional[_SceneReconImageGenJob]:
    """Enqueue an imagegen job that chains into scene reconstruction.

    Args:
        prompt: User-visible prompt (used for label).
        stored_prompt: Full prompt with suffix (sent to backend).
        recon_params: kwargs dict forwarded to ``submit_recon_job``.
        sidebar_available: Whether sidebar_tab should be resolved on completion.
        on_error: Called if the imagegen job fails at any lifecycle stage.

    Returns:
        The enqueued job, or None if dedup rejected it.
    """
    job = _SceneReconImageGenJob(
        feature_key=FEATURE_IMAGEGEN,
        label=f"SceneRecon: {prompt[:40]}",
        prompt=stored_prompt or prompt,
        model="pro",
        aspect_ratio="4:3",
        resolution="1K",
        num_images=1,
        _stored_prompt=stored_prompt or prompt,
        _recon_params=recon_params,
        _sidebar_available=sidebar_available,
    )
    queue = get_queue(FEATURE_IMAGEGEN)
    if not queue.submit(job):
        logger.warning(
            "[SceneRecon] duplicate imagegen job rejected: %s", job.label,
        )
        return None

    if on_error:
        _watch_for_failure(job.id, on_error)

    return job


# ---------------------------------------------------------------------------
# Failure watcher
# ---------------------------------------------------------------------------


def _watch_for_failure(
    job_id: str, on_error: Callable[[str], None],
) -> None:
    """One-shot IMAGEGEN queue listener that fires *on_error* if the job fails.

    Self-removes once the job reaches any terminal state.
    """
    queue = get_queue(FEATURE_IMAGEGEN)

    def _listener(q):
        for j in q.snapshot():
            if j.id != job_id:
                continue
            if j.state == JobState.FAILED:
                q.remove_listener(_listener)
                on_error(j.error or "Image generation failed")
            elif j.state in TERMINAL_STATES:
                q.remove_listener(_listener)
            return

    queue.add_listener(_listener)

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image result transfer: parallel download + batched moodboard apply.

One job's result urls download CONCURRENTLY (pool capped at 4) into
indexed slots so board order equals URL order no matter which transfer
finishes first; the main-thread _apply stays ONE batch so the undo push,
the on_added provenance hook and on_done each fire exactly once per job.
Latency contract pinned in tests/test_job_queue_image_results.py and
documented in CLAUDE.md's Unified Job Queue section.
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Image download + moodboard add
# ---------------------------------------------------------------------------


def download_images_to_moodboard(
    *,
    urls: list,
    name_prefix: str,
    prompt: str,
    job_id: str,
    on_added=None,
    on_done,
    on_error,
    undo_message: str = "",
    base_name: str = "",
    scene_name: str = "",
    should_apply=None,
) -> None:
    """Download images from URLs in bg thread, add to moodboard on main thread.

    Parameters
    ----------
    urls : list[str]
        Image URLs to download.
    name_prefix : str
        Prefix for bpy.data.images names (e.g. ``"imagegen"``).
    prompt : str
        Prompt text stored with the moodboard entry.
    job_id : str
        Job ID for moodboard handle tracking.
    on_done : callable(names_str)
        Called on main thread with comma-separated image names.
    on_added : callable(names_str), optional
        Called after moodboard insertion but before the undo snapshot. Use for
        durable metadata/placement that redo must restore with the image.
        Failure rolls back the new cards and image datablocks.
    on_error : callable(error_str)
        Called on main thread if all downloads fail.
    undo_message : str, optional
        If set, pushes an undo step with this message after adding images.
    scene_name : str, optional
        Originating Blender scene. Queue jobs set this so changing the active
        scene while a download runs cannot redirect the generated images.
    should_apply : callable, optional
        Main-thread cancellation guard. When false, downloaded temp files are
        discarded without inserting images or firing completion callbacks.
    """

    def _bg_download():
        try:
            from mixar.modules.common.utils.image_utils import (
                download_image_to_tempfile,
                filename_from_url,
            )

            batch_started_at = time.time()

            def _fetch(i, url):
                try:
                    s3_filename = filename_from_url(url)
                    if base_name:
                        # Agent-chosen or backend-suggested name. Blender auto-dedups collisions
                        # (e.g. "dog" -> "dog.001"); index only when >1 image.
                        name = base_name if len(urls) == 1 else f"{base_name}_{i + 1}"
                    elif s3_filename:
                        # No suggested name — mirror the server-side S3 file
                        # name (prompt-derived, unique per image) so outliner
                        # name, filepath and S3 key stay aligned.
                        name = os.path.splitext(s3_filename)[0]
                    else:
                        timestamp = int(time.time())
                        name = f"{name_prefix}_{timestamp}_{i}"
                    download_started_at = time.time()
                    # Keep the server-side (S3) file name on the temp file so
                    # the packed datablock's filepath shows the same name.
                    temp_path, byte_count = download_image_to_tempfile(
                        url, filename=s3_filename,
                    )
                    logger.debug(
                        "[Queue] image download completed job=%s index=%d bytes=%d duration=%.3fs",
                        job_id,
                        i,
                        byte_count,
                        time.time() - download_started_at,
                    )
                    return (temp_path, name, byte_count)
                except Exception as e:
                    logger.error("Failed to download image %d: %s", i, e)
                    return None

            # Parallel transfers, bounded: a multi-image result used to queue
            # every file on one socket after the other, so the board stayed
            # blank until the LAST image landed. Indexed slots keep insertion
            # order identical to URL order no matter which transfer wins the
            # race, and the worker cap bounds memory/network pressure the
            # same way the old serial loop did.
            slots = [None] * len(urls)
            with ThreadPoolExecutor(
                max_workers=max(1, min(4, len(urls)))
            ) as pool:
                futures = [
                    pool.submit(_fetch, i, url)
                    for i, url in enumerate(urls)
                ]
                for i, future in enumerate(futures):
                    slots[i] = future.result()
            downloaded_files = [entry for entry in slots if entry is not None]

            def _apply():
                if not downloaded_files:
                    on_error("Failed to download generated images")
                    return None
                from mixar.modules.common.utils.image_utils import (
                    add_image_to_moodboard,
                    cleanup_temp_image,
                    load_image_from_file,
                )

                if should_apply is not None and not should_apply():
                    for temp_path, _name, _byte_count in downloaded_files:
                        cleanup_temp_image(temp_path)
                    return None

                loaded_images = []
                for temp_path, name, byte_count in downloaded_files:
                    load_started_at = time.time()
                    try:
                        img = load_image_from_file(
                            temp_path, name, keep_filename=True,
                        )
                        logger.debug(
                            "[Queue] image load completed job=%s image=%s bytes=%d duration=%.3fs total=%.3fs",
                            job_id,
                            img.name,
                            byte_count,
                            time.time() - load_started_at,
                            time.time() - batch_started_at,
                        )
                        loaded_images.append(img)
                    except Exception as e:
                        logger.error("Failed to load image into Blender: %s", e)
                    finally:
                        cleanup_temp_image(temp_path)

                if not loaded_images:
                    on_error("Failed to load generated images")
                    return None

                target_scene = None
                if scene_name:
                    try:
                        target_scene = bpy.data.scenes.get(scene_name)
                    except Exception:
                        target_scene = None
                    if target_scene is None:
                        for img in loaded_images:
                            try:
                                bpy.data.images.remove(img)
                            except Exception:
                                pass
                        on_error(f"Originating scene '{scene_name}' no longer exists")
                        return None
                else:
                    target_scene = getattr(bpy.context, "scene", None)
                if target_scene is None:
                    for img in loaded_images:
                        try:
                            bpy.data.images.remove(img)
                        except Exception:
                            pass
                    on_error("No Blender scene is available for generated images")
                    return None

                added_images = []
                for img in loaded_images:
                    try:
                        add_image_to_moodboard(
                            img,
                            prompt,
                            job_handle=job_id,
                            scene=target_scene,
                        )
                        added_images.append(img)
                    except Exception as e:
                        logger.error(
                            "Failed to add image to moodboard: %s", e,
                        )
                        try:
                            bpy.data.images.remove(img)
                        except Exception:
                            pass

                if not added_images:
                    on_error("Failed to add generated images to the moodboard")
                    return None

                names = ", ".join(img.name for img in added_images)
                if on_added is not None:
                    try:
                        on_added(names)
                    except Exception as e:
                        # Metadata hooks may be part of the result contract
                        # (for example, character-component provenance). Roll
                        # back the cards and their freshly loaded datablocks so
                        # a failed hook cannot leave a successful-looking,
                        # untraceable result on the moodboard.
                        try:
                            items = target_scene.mixie_moodboard_images
                            for index in range(len(items) - 1, -1, -1):
                                try:
                                    item = items[index]
                                    if (
                                        getattr(item, "mixar_job_handle", "") == job_id
                                        and getattr(item, "image", None) in added_images
                                    ):
                                        items.remove(index)
                                except Exception:
                                    pass
                            for img in added_images:
                                try:
                                    bpy.data.images.remove(img)
                                except Exception:
                                    pass
                        except Exception as rollback_error:
                            # The rollback must never mask on_error: a raise
                            # here would otherwise strand the job in
                            # RUNNING_DOWNLOAD and leak the loaded datablocks.
                            logger.error(
                                "Moodboard rollback failed for job %s: %s",
                                job_id, rollback_error,
                            )
                        on_error(f"Could not finalize generated images: {e}")
                        return None
                if undo_message:
                    bpy.ops.ed.undo_push(message=undo_message)
                logger.debug(
                    "[Queue] image moodboard update completed job=%s count=%d total=%.3fs",
                    job_id,
                    len(added_images),
                    time.time() - batch_started_at,
                )
                on_done(names)
                return None

            bpy.app.timers.register(_apply, first_interval=0.0)
        except Exception as e:
            err = f"Unexpected error during image download: {e}"
            logger.error(err)

            def _fail():
                on_error(err)
                return None

            bpy.app.timers.register(_fail, first_interval=0.0)

    threading.Thread(target=_bg_download, daemon=True).start()

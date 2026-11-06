# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Local persistence and visible completion for requested scene renders."""
import os

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import rpt_
from mixar.modules.common.notifications import get_notification_store

logger = get_logger(__name__)


def notify(key, kind, status, body="", to_file=False):
    """``to_file``: an Export card render, saved to the user's file."""
    try:
        store = get_notification_store()
        video = kind == 'video'
        if to_file:
            done = rpt_("Video saved") if video else rpt_("Image saved")
        else:
            done = rpt_("Video added to Moodboard") if video else rpt_("Image added to Moodboard")
        title = {"started": rpt_("Rendering video") if video else rpt_("Rendering image"),
                 "done": done,
                 "cancelled": rpt_("Render cancelled"), "failed": rpt_("Render failed")}[status]
        store.push('success' if status == 'done' else 'error' if status == 'failed' else 'info',
                   title, body=body, id='scene-render-' + key, ttl_ms=0 if status == 'started' else 8000)
    except Exception:
        logger.exception("Scene render notification failed")


def deliver_file(job):
    """Save the finished render to the Export card's chosen file (replacing
    one of that name) and return its basename. A video moves out of the job's
    temp folder; a still is written from Render Result in the format the job
    applied (`Settings.apply(image_format=…)`)."""
    import shutil
    destination = job['destination']
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    if job['kind'] == 'video':
        paths = [os.path.join(job['folder'], name) for name in os.listdir(job['folder'])
                 if name.lower().endswith('.mp4')]
        if len(paths) != 1 or os.path.getsize(paths[0]) == 0:
            raise RuntimeError('output_unavailable')
        if os.path.exists(destination):
            os.remove(destination)
        shutil.move(paths[0], destination)
    else:
        image = bpy.data.images.get('Render Result')
        if image is None or not image.has_data:
            raise RuntimeError('output_unavailable')
        image.save_render(destination, scene=job['scene'])
    return os.path.basename(destination)


def deliver(job):
    scene = job['scene']
    # Do not fall back to whichever scene happens to be active on completion.
    if not any(s == scene for s in bpy.data.scenes):
        raise RuntimeError('scene_unavailable')
    label = job['label'] or ('Scene video' if job['kind'] == 'video' else 'Scene render')
    if job['kind'] == 'video':
        from mixar.modules.moodboard.core.media_import import import_generated_video
        paths = [os.path.join(job['folder'], name) for name in os.listdir(job['folder'])
                 if name.lower().endswith('.mp4')]
        if len(paths) != 1 or os.path.getsize(paths[0]) == 0:
            raise RuntimeError('output_unavailable')
        name = import_generated_video(paths[0], scene_name=scene.name,
                                      generation_prompt=label, display_name=label)
        item = next(i for i in scene.mixie_moodboard_images if i.image and i.image.name == name)
        item.mixar_job_handle = job['key']
    else:
        from mixar.modules.moodboard.core.media_import import pack_still_image
        from mixar.modules.common.utils.image_utils import add_image_to_moodboard
        image = bpy.data.images.get('Render Result')
        if image is None or not image.has_data:
            raise RuntimeError('output_unavailable')
        image.save_render(job['path'], scene=scene)
        packed = pack_still_image(job['path'], display_name=label)
        try:
            add_image_to_moodboard(packed, prompt=label, scene=scene, job_handle=job['key'])
        except Exception:
            # A redraw may fail after the helper has already placed the packed image.
            if not any(i.image == packed for i in scene.mixie_moodboard_images):
                bpy.data.images.remove(packed)
                raise
        name = packed.name
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    return name

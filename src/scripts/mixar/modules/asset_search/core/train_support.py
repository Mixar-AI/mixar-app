# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Small main-thread helpers shared by the training operators."""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def fmt_duration(seconds):
    """Human duration: 42s / 3m 07s / 1h 04m."""
    seconds = max(int(seconds), 0)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def set_failures(state, failures):
    """Publish (label, reason) pairs to the panel (capped, readable)."""
    state.failed_count = len(failures)
    lines = [f"{label} — {reason}" for label, reason in failures[:10]]
    if len(failures) > 10:
        lines.append(f"…and {len(failures) - 10} more (see console)")
    state.failed_list = "\n".join(lines)


def launch_thumbnail_backfill(rendered_items):
    """Write the session's rendered previews back as asset thumbnails.

    ``rendered_items``: RenderSession.rendered_items — assets that were
    RENDERED because their .blend carried no usable preview. Their packed
    JPEGs are written to a temp dir and a fire-and-forget backfill worker
    (separate process) injects them into the source .blend files, so the
    assets get real thumbnails and the next training run reuses them.
    Best-effort: any failure just leaves the library as it was.
    """
    import os
    import tempfile

    from mixar.modules.asset_search.core import preview_worker

    entries = []
    try:
        work_dir = None
        for i, item in enumerate(rendered_items):
            img = bpy.data.images.get(item.get("image_name", ""))
            if img is None:
                continue
            data = extract_image_bytes(img)
            if not data:
                continue
            if work_dir is None:
                work_dir = tempfile.mkdtemp(prefix="mixar_backfill_")
            jpg = os.path.join(work_dir, f"{i:05d}.jpg")
            with open(jpg, "wb") as fh:
                fh.write(data)
            entries.append({
                "blend_str": item["blend_str"], "name": item["name"], "jpg": jpg,
            })
        preview_worker.start_backfill(entries)
    except Exception as e:  # noqa: BLE001 — thumbnails are a bonus, never a blocker
        logger.warning("[Asset Training] Thumbnail backfill skipped: %s", e)


def extract_image_bytes(img):
    """Extract JPEG bytes from a Blender image (packed fast path)."""
    if img.packed_file and img.packed_file.data:
        return bytes(img.packed_file.data)

    import os
    import tempfile

    from mixar.modules.asset_search.utils.preview_render import safe_temp_filename

    tmp_path = os.path.join(
        tempfile.gettempdir(), f"_mixar_tmp_{safe_temp_filename(img.name)}.jpg"
    )
    try:
        img.save_render(filepath=tmp_path)
        with open(tmp_path, "rb") as fh:
            return fh.read()
    except Exception as exc:
        logger.error("[Asset Training] Fallback save failed for %s: %s", img.name, exc)
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Small main-thread helpers shared by the training operators."""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Progress-bar weighting per phase (render dominates wall time). Shared, since
# the modal and each of its phase modules report against the same scale.
W_SCAN_END = 0.05
W_PREPARE_END = 0.08
W_RENDER_END = 0.80


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
    RENDERED because their .blend carried no usable preview. Their JPEGs are
    COPIED into a temp dir of their own and a fire-and-forget backfill worker
    (separate process) injects them into the source .blend files, so the assets
    get real thumbnails and the next training run reuses them.

    The copy is deliberate: the backfill worker deletes its own work dir when
    it finishes, and the originals still have to be there for the upload.
    Best-effort — any failure just leaves the library as it was.
    """
    import os
    import shutil
    import tempfile

    from mixar.modules.asset_search.core import preview_worker

    entries = []
    try:
        work_dir = None
        for i, item in enumerate(rendered_items):
            source = item.get("jpg", "")
            if not source or not os.path.isfile(source):
                continue
            if work_dir is None:
                work_dir = tempfile.mkdtemp(prefix="mixar_backfill_")
            jpg = os.path.join(work_dir, f"{i:05d}.jpg")
            shutil.copyfile(source, jpg)
            entries.append({
                "blend_str": item["blend_str"], "name": item["name"], "jpg": jpg,
            })
        preview_worker.start_backfill(entries)
    except Exception as e:  # noqa: BLE001 — thumbnails are a bonus, never a blocker
        logger.warning("[Asset Training] Thumbnail backfill skipped: %s", e)

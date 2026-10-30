# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Small main-thread helpers shared by the training operators."""

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import iface_

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
        lines.append(iface_("…and {count} more (see console)").format(count=len(failures) - 10))
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
            entry = {"blend_str": item["blend_str"], "name": item["name"], "jpg": jpg}
            if item.get("kind"):
                entry["kind"] = item["kind"]  # MATERIAL; objects carry none
            entries.append(entry)
        watch_backfill(preview_worker.start_backfill(entries))
    except Exception as e:  # noqa: BLE001 — thumbnails are a bonus, never a blocker
        logger.warning("[Asset Training] Thumbnail backfill skipped: %s", e)


# Poll backoff for a running backfill: a check is one non-blocking
# ``Popen.poll()``, and a library rewrite takes seconds to minutes.
_BACKFILL_POLL_S = (1.0, 2.0, 5.0)
_BACKFILL_GIVE_UP_S = 30 * 60


def watch_backfill(proc):
    """When the backfill process exits, tell the Library pane to re-read the
    connected libraries so the new thumbnails show without a restart.

    A ``bpy.app.timers`` poll on the main thread: one ``Popen.poll()`` per
    tick, backing off to 5 s, stopping at exit or after 30 minutes.
    """
    if proc is None:
        return
    import time

    import bpy

    started = time.monotonic()
    ticks = [0]

    def _poll():
        if proc.poll() is None:
            if time.monotonic() - started > _BACKFILL_GIVE_UP_S:
                return None
            ticks[0] += 1
            return _BACKFILL_POLL_S[min(ticks[0], len(_BACKFILL_POLL_S) - 1)]
        try:
            from mixar.modules.agent_bubble.ui.properties.generations_props import (
                bump_library_revision,
            )
            bump_library_revision()
        except Exception as exc:  # noqa: BLE001 — a repaint is never worth a failure
            logger.debug("[Asset Training] library revision bump skipped: %s", exc)
        return None

    bpy.app.timers.register(_poll, first_interval=_BACKFILL_POLL_S[0])

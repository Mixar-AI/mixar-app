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

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Custom status-dot icons for the unified queue UIList.

Generates four small antialiased circle PNGs (green filled, green ring,
grey filled, red filled) and loads them via ``bpy.utils.previews`` — the
same well-tested path Blender's own addons use. The PNGs live in the
user's tempdir and are regenerated once per Mixar boot.

Icon generation is deferred to a ``bpy.app.timers`` tick so it never
runs inside a ``draw_item`` callback — mutating ``bpy.data`` mid-draw
crashes Blender.  ``get_icon_id()`` returns 0 until the deferred load
completes; the UIList already falls back to a built-in icon in that
window.  Same pattern as ``agent_bubble/pill_icons``.
"""

from __future__ import annotations

import os
import tempfile

import bpy
import bpy.utils.previews

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue.core.job import JobState, RUNNING_STATES

_logger = get_logger(__name__)

_SIZE = 64

# Visible dot occupies 80% of the icon canvas (transparent padding around
# it) — Blender renders preview icons scaled-to-fit the label line height,
# so on-screen this reads ~20% smaller than a canvas-filling dot.
_DOT_FILL_RATIO = 0.8

# Linear-light RGB for the dot fill / ring stroke.
_GREEN = (0.30, 0.85, 0.45)
_GREY = (0.45, 0.45, 0.50)
_RED = (1.00, 0.36, 0.34)

# Filename suffix — bump when the pixel layout changes so cached PNGs
# from a previous Mixar boot get regenerated at the new size.
_ICON_VERSION = "v2"

# Names loaded into the previews collection.
_NAME_GREEN_FILLED = f"green_filled_{_ICON_VERSION}"
_NAME_GREEN_RING = f"green_ring_{_ICON_VERSION}"
_NAME_GREY_FILLED = f"grey_filled_{_ICON_VERSION}"
_NAME_RED_FILLED = f"red_filled_{_ICON_VERSION}"

_pcoll = None

# ---------------------------------------------------------------------------
# Blink state — running jobs alternate filled ↔ ring on a 500 ms cycle.
# ---------------------------------------------------------------------------

_BLINK_INTERVAL_S = 0.5
_blink_phase = False
_blink_timer_active = False

_RUNNING_STATE_VALUES = frozenset(s.value for s in RUNNING_STATES)


def _make_pixels(color, filled: bool, size: int = _SIZE):
    """Return a flat RGBA float list for a filled or ring circle.

    ``filled=True`` -> antialiased solid disk.
    ``filled=False`` -> antialiased ring (hollow), ~4 px stroke.
    """
    cx = (size - 1) * 0.5
    cy = (size - 1) * 0.5
    outer = ((size * 0.5) - 2.0) * _DOT_FILL_RATIO
    inner = outer - 4.0  # ring thickness (only used when filled=False)
    r, g, b = color
    pixels = []
    for y in range(size):
        for x in range(size):
            dx = x - cx
            dy = y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if filled:
                if dist <= outer - 0.5:
                    a = 1.0
                elif dist <= outer + 0.5:
                    a = max(0.0, outer + 0.5 - dist)
                else:
                    a = 0.0
            else:
                # Ring: inside outer edge but outside inner edge.
                a_outer = 1.0 if dist <= outer - 0.5 else (
                    max(0.0, outer + 0.5 - dist) if dist <= outer + 0.5 else 0.0
                )
                a_inner = 0.0 if dist <= inner - 0.5 else (
                    min(1.0, dist - (inner - 0.5)) if dist <= inner + 0.5 else 1.0
                )
                a = a_outer * a_inner
            pixels.extend([r, g, b, a])
    return pixels


def _write_png(filepath: str, color, filled: bool) -> bool:
    tmp_name = "_mixar_queue_dot_tmp"
    stale = bpy.data.images.get(tmp_name)
    if stale is not None:
        try:
            bpy.data.images.remove(stale)
        except Exception:
            pass
    img = bpy.data.images.new(tmp_name, _SIZE, _SIZE, alpha=True, float_buffer=False)
    try:
        img.pixels = _make_pixels(color, filled)
        img.update()
        img.filepath_raw = filepath
        img.file_format = 'PNG'
        img.save()
    except Exception as e:
        _logger.warning("queue_status_icons: PNG save failed (%s): %s", filepath, e)
        try:
            bpy.data.images.remove(img)
        except Exception:
            pass
        return False
    try:
        bpy.data.images.remove(img)
    except Exception:
        pass
    return True


def _build_previews() -> None:
    """Generate PNGs and load them via bpy.utils.previews. Never call from draw."""
    global _pcoll
    if _pcoll is not None:
        return
    try:
        cache_dir = os.path.join(tempfile.gettempdir(), "mixar_queue_dots")
        os.makedirs(cache_dir, exist_ok=True)
    except Exception as e:
        _logger.warning("queue_status_icons: tempdir failed: %s", e)
        return

    specs = (
        (_NAME_GREEN_FILLED, _GREEN, True),
        (_NAME_GREEN_RING, _GREEN, False),
        (_NAME_GREY_FILLED, _GREY, True),
        (_NAME_RED_FILLED, _RED, True),
    )
    pcoll = bpy.utils.previews.new()
    for name, color, filled in specs:
        png = os.path.join(cache_dir, name + ".png")
        needs_write = True
        try:
            needs_write = os.path.getsize(png) <= 0
        except OSError:
            pass
        if needs_write and not _write_png(png, color, filled):
            continue
        try:
            pcoll.load(name, png, "IMAGE")
        except KeyError:
            pass
        except Exception as e:
            _logger.warning("queue_status_icons: load failed (%s): %s", name, e)
    _pcoll = pcoll


def _deferred_register_tick():
    """Timer callback — runs on the main thread, outside of any draw."""
    _build_previews()
    return None  # don't re-fire


def register() -> None:
    """Schedule preview generation for the next main-thread tick.

    Blender crashes if ``bpy.data`` is mutated during a draw callback,
    so we never touch ``bpy.utils.previews`` / ``bpy.data.images`` from
    ``get_icon_id`` — the preload runs once via ``bpy.app.timers``.
    """
    if _pcoll is not None:
        return
    if not bpy.app.timers.is_registered(_deferred_register_tick):
        bpy.app.timers.register(_deferred_register_tick, first_interval=1.0)


_STATE_TO_ICON_NAME = {
    JobState.RUNNING_SUBMIT.value: _NAME_GREEN_FILLED,
    JobState.RUNNING_POLL.value: _NAME_GREEN_FILLED,
    JobState.RUNNING_DOWNLOAD.value: _NAME_GREEN_FILLED,
    JobState.SUCCESS.value: _NAME_GREEN_RING,
    JobState.PENDING.value: _NAME_GREY_FILLED,
    JobState.PAUSED_AUTH.value: _NAME_GREY_FILLED,
    JobState.CANCELLED.value: _NAME_GREY_FILLED,
    JobState.FAILED.value: _NAME_RED_FILLED,
}


def get_icon_id(state_value: str) -> int:
    """Return the preview icon_id for a JobState string.

    Safe to call from ``draw_item``: returns 0 while the deferred
    preview generation is still pending, and never mutates ``bpy.data``.
    Callers should fall back to a built-in icon when this returns 0.

    Running states blink — the dot alternates between the filled and
    the ring variant every ``_BLINK_INTERVAL_S`` seconds, driven by
    ``_blink_tick``.
    """
    if _pcoll is None:
        return 0
    if state_value in _RUNNING_STATE_VALUES:
        name = _NAME_GREEN_RING if _blink_phase else _NAME_GREEN_FILLED
    else:
        name = _STATE_TO_ICON_NAME.get(state_value, _NAME_GREY_FILLED)
    entry = _pcoll.get(name)
    return entry.icon_id if entry is not None else 0


# ---------------------------------------------------------------------------
# Blink pump
# ---------------------------------------------------------------------------


def _has_running_jobs() -> bool:
    """Any FeatureQueue with at least one job that still has work to do.

    Deliberately the ACTIVE set (pending + paused included), not just
    RUNNING_*: the pump also drives the Agent Bubble pill's animated label,
    and a job that is queued-but-not-yet-dispatched must not leave the pill
    frozen. The icon mapping is unchanged — only RUNNING_* rows blink.
    """
    try:
        from mixar.modules.common.job_queue.core.queue_manager import (
            ACTIVE_JOB_STATES,
            all_queues,
        )
    except Exception:
        return False
    for q in all_queues():
        for job in q.snapshot():
            if job.state in ACTIVE_JOB_STATES:
                return True
    return False


def _redraw_queue_areas() -> None:
    """Tag every surface that renders queue state so the new phase paints.

    This pump is also the only recurring tick while jobs run, so it drives
    the Agent Bubble pill's "Generating…" dot animation — hence the shared
    surface list (which includes AGENT_BUBBLE) rather than a local one.
    """
    try:
        from mixar.modules.common.job_queue.core.model_io import (
            tag_redraw_queue_surfaces,
        )
        tag_redraw_queue_surfaces()
    except Exception:
        pass


def _blink_tick():
    """Timer callback — flip phase and force redraw while jobs are running."""
    global _blink_phase, _blink_timer_active
    if not _has_running_jobs():
        # No work left — settle on the filled dot and stop the pump so we
        # don't burn redraws once the queue goes idle.
        _blink_phase = False
        _blink_timer_active = False
        _redraw_queue_areas()
        return None
    _blink_phase = not _blink_phase
    _redraw_queue_areas()
    return _BLINK_INTERVAL_S


def start_blink_if_needed() -> None:
    """Kick off the blink timer if there's running work and it isn't already.

    The flag is trusted only when the timer really is registered. It used to
    be trusted on its own, and a file load then froze the queue for the rest
    of the session: Blender drops non-persistent timers on load, but nothing
    cleared the flag, so both restart paths returned here and the pill's
    elapsed clock stayed stuck at whatever it read at load time. The timer is
    persistent now AND the flag is cross-checked, so neither alone can wedge
    it.
    """
    global _blink_timer_active
    if _blink_timer_active and bpy.app.timers.is_registered(_blink_tick):
        return
    if not _has_running_jobs():
        _blink_timer_active = False
        return
    _blink_timer_active = True
    try:
        bpy.app.timers.register(
            _blink_tick, first_interval=_BLINK_INTERVAL_S, persistent=True
        )
    except Exception:
        _blink_timer_active = False


def unregister() -> None:
    """Tear down the previews collection on Mixar shutdown."""
    global _pcoll, _blink_timer_active, _blink_phase
    for cb in (_deferred_register_tick, _blink_tick):
        try:
            if bpy.app.timers.is_registered(cb):
                bpy.app.timers.unregister(cb)
        except Exception:
            pass
    _blink_timer_active = False
    _blink_phase = False
    if _pcoll is not None:
        try:
            bpy.utils.previews.remove(_pcoll)
        except Exception as e:
            _logger.warning("queue_status_icons: previews.remove failed: %s", e)
        _pcoll = None

# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Generate Button Progress Animation

Timer-driven progress bar for generative feature buttons.
Animates a slow fill while generating (caps at 75%), then fast-fills
to 100% on completion.
"""

import bpy
import threading
from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.mixie_space_utils import redraw_mixie_areas

logger = get_logger(__name__)

# Animation constants
_TICK_INTERVAL = 0.016       # ~60 fps
_SLOW_RATE = 0.75 / 30.0    # Reaches 0.75 in ~30 seconds
_FAST_RATE = 3.0             # Fills remaining 0.25 in ~0.08s
_PROGRESS_CAP = 0.75         # Max progress during slow phase

# All tab prefixes that support progress
_ALL_PREFIXES = ('imagegen', 'lookdev', 'lookdev360', 'image_to_3d', 'scene_recon',
                 'segment_to_3d', 'mesh_segment', 'retopology',
                 'tripo_segment', 'smart_segment',
                 'scene_gen_hp', 'scene_gen_lp')

# Non-standard scene flag names (default pattern: mixie_{prefix}_is_generating)
_GEN_FLAG_OVERRIDES = {
    'mesh_segment': 'mixie_mesh_segment_is_processing',
}

# Module state
_timer_running = False
_completing = set()  # Prefixes in fast-fill phase
_completing_lock = threading.Lock()


def _progress_tick():
    """Timer callback: advance progress for all active tabs."""
    global _timer_running

    try:
        wm = bpy.context.window_manager
        scene = bpy.context.scene

        # Early exit: nothing is generating and no completions pending
        with _completing_lock:
            has_completing = bool(_completing)
        if not has_completing:
            if not any(
                getattr(scene, _GEN_FLAG_OVERRIDES.get(p, f'mixie_{p}_is_generating'), False)
                for p in _ALL_PREFIXES
            ):
                _timer_running = False
                return None

        any_active = False

        for prefix in _ALL_PREFIXES:
            prog_attr = f'mixie_{prefix}_generate_progress'
            gen_attr = _GEN_FLAG_OVERRIDES.get(prefix, f'mixie_{prefix}_is_generating')
            progress = getattr(wm, prog_attr, 0.0)
            is_gen = getattr(scene, gen_attr, False)

            with _completing_lock:
                in_completing = prefix in _completing
            if in_completing:
                # Fast-fill phase: advance quickly toward 1.0
                progress += _FAST_RATE * _TICK_INTERVAL
                if progress >= 1.0:
                    setattr(wm, prog_attr, 0.0)
                    with _completing_lock:
                        _completing.discard(prefix)
                else:
                    setattr(wm, prog_attr, progress)
                    any_active = True

            elif is_gen:
                # Slow phase: advance linearly, cap at 0.75
                progress = min(progress + _SLOW_RATE * _TICK_INTERVAL, _PROGRESS_CAP)
                setattr(wm, prog_attr, progress)
                any_active = True

            elif progress > 0.0:
                # Fallback: is_generating is False but progress wasn't reset
                setattr(wm, prog_attr, 0.0)

        if any_active:
            redraw_mixie_areas()
            return _TICK_INTERVAL

        # No tabs active — stop timer
        redraw_mixie_areas()
        _timer_running = False
        return None

    except Exception as e:
        logger.debug("Progress tick error: %s", e)
        _timer_running = False
        return None


def _ensure_timer_running():
    """Must be called from the main thread only. _timer_running is not lock-protected."""
    global _timer_running
    if _timer_running or bpy.app.timers.is_registered(_progress_tick):
        return
    _timer_running = True
    bpy.app.timers.register(_progress_tick, first_interval=_TICK_INTERVAL)


def start_progress(tab_prefix):
    """Begin slow-fill progress for a tab."""
    try:
        wm = bpy.context.window_manager
        prog_attr = f'mixie_{tab_prefix}_generate_progress'
        if hasattr(wm, prog_attr):
            setattr(wm, prog_attr, 0.0)
        with _completing_lock:
            _completing.discard(tab_prefix)
        _ensure_timer_running()
    except Exception as e:
        logger.debug("start_progress error: %s", e)


def complete_progress(tab_prefix):
    """Trigger fast-fill to 100% for a tab (called on success)."""
    try:
        with _completing_lock:
            _completing.add(tab_prefix)
        _ensure_timer_running()
    except Exception as e:
        logger.debug("complete_progress error: %s", e)


def reset_progress(tab_prefix):
    """Immediately zero out progress (called on error/cancel)."""
    try:
        wm = bpy.context.window_manager
        prog_attr = f'mixie_{tab_prefix}_generate_progress'
        if hasattr(wm, prog_attr):
            setattr(wm, prog_attr, 0.0)
        with _completing_lock:
            _completing.discard(tab_prefix)
    except Exception as e:
        logger.debug("reset_progress error: %s", e)

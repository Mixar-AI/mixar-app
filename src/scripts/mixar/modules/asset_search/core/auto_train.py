# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Debounced, single-flight auto-training.

Kicks an incremental embedding train — ``mixie.train_asset_model(auto=True)``,
which is silent when nothing changed — whenever the ENROLLED asset libraries are
altered: a library is enrolled/unenrolled, a file is opened, an asset is saved,
or (via generation_library) a generation is archived. The train's own
``/train/prepare`` no-ops when there is no diff, so callers schedule liberally
and this scheduler coalesces bursts into one run.

Single-flight: one latch, one pending timer at a time. The timer waits out any
manual or auto train already running (`is_training`) before firing, so
auto-training never overlaps a run in progress.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_scheduled = False
# ~60 * 2s = 2 min max wait for a busy manual train to finish before giving up
# (the next change reschedules).
_MAX_WAIT_TICKS = 60


def schedule_auto_train(reason: str = "", allow_empty: bool = False) -> None:
    """Schedule ONE debounced auto-train. No-op when already scheduled, or when
    nothing is enrolled UNLESS ``allow_empty`` — which the unenroll trigger sets
    so unenrolling the LAST library still runs a train that drops its now-orphaned
    embeddings (an auto-train with an empty scan takes the removal path)."""
    global _scheduled
    if _scheduled:
        return
    if not allow_empty:
        try:
            from mixar.modules.asset_search.core.library_enrollment import (
                enrolled_names,
            )
            if not enrolled_names():
                return
        except Exception:  # noqa: BLE001 — if we can't tell, fall through and train
            pass

    _scheduled = True
    state = {"ticks": 0}

    def _tick():
        global _scheduled
        # Wait out any train in progress FIRST, outside the try/finally, so the
        # latch stays set while we poll (clearing it mid-flight would let a
        # second change register another timer — the retrain-storm bug).
        training = getattr(bpy.context.scene, "mixie_asset_training", None)
        if training is not None and getattr(training, "is_training", False):
            state["ticks"] += 1
            if state["ticks"] > _MAX_WAIT_TICKS:
                _scheduled = False
                return None  # give up; the next change reschedules
            return 2.0  # a train is running — poll back (latch stays SET)

        try:
            win = bpy.context.window
            if win is None:
                wm = bpy.context.window_manager
                win = wm.windows[0] if wm and wm.windows else None
            if win is not None:
                with bpy.context.temp_override(window=win, screen=win.screen):
                    bpy.ops.mixie.train_asset_model(auto=True)
            else:
                bpy.ops.mixie.train_asset_model(auto=True)
            logger.info("[AutoTrain] triggered (%s)", reason or "change")
        except Exception:
            logger.exception("[AutoTrain] could not start")
        finally:
            _scheduled = False
        return None  # one-shot

    # 1s debounce so a burst of enrollment toggles coalesces into one train.
    bpy.app.timers.register(_tick, first_interval=1.0)

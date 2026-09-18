# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mic button as a `UILayout` row, for the N-panel generation tabs.

The mic is ONE control that appears in four places, and it looks and animates
the same in all of them. The C++ surfaces (chat composer, Agent Bubble,
moodboard node tile) paint it with `ED_mixar_voice_draw_button`; a sidebar panel
is `UILayout` all the way down with no GPU pass to hang that on, so this one
draws the identical shapes rasterized into a preview icon
(`core/glyph_raster.py` + `core/glyph_icons.py`) and steps through frames as the
level and the clock move.

Stock `ICON_*` is the fallback, not the design: it is what draws on a build
where the preview collection could not be allocated. Before this the sidebar
used three static stock icons, which is how the same control came to read as
three different things depending on where you found it.

ONE definition, called from `draw_prompt_section` — the single boxed prompt
every generation tab draws — so every prompt-bearing tab gains dictation from
one place and none of them can end up with a mic that behaves differently.
"""

from __future__ import annotations

import time

from mixar.config.logging_config import get_logger

from ..constants import (
    MAX_RECORDING_SECONDS,
    STATE_ERROR,
    STATE_IDLE,
    STATE_RECORDING,
    STATE_TRANSCRIBING,
)
from ..core import glyph_icons
from ..core.targets import target_for_tab

logger = get_logger(__name__)

#: Stock icons per state, used ONLY when the rasterized glyph is unavailable.
#: A microphone is not in Blender's icon set, which is the whole reason the
#: custom glyph exists — idle falls back to the audio glyph (`SOUND`) and
#: recording to the record dot every Blender surface spells "capturing" with.
_FALLBACK_ICONS = {
    STATE_IDLE: 'SOUND',
    STATE_RECORDING: 'REC',
    STATE_TRANSCRIBING: 'SORTTIME',
    STATE_ERROR: 'ERROR',
}


def _format_clock(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def draw_mic_button(layout, context, target: str) -> None:
    """Draw the mic control for `target` into `layout` (a row is added).

    Silent no-op when the capture engine is missing — an older build, or one
    compiled without it. A dead button is worse than none.
    """
    wm = getattr(context, "window_manager", None)
    if wm is None or not getattr(wm, "mixar_audio_available", False):
        return

    state = getattr(wm, "mixar_voice_state", STATE_IDLE)
    active_target = getattr(wm, "mixar_voice_target", "")
    # Another field's recording must not light up THIS tab's mic: the words are
    # going somewhere else, and a second lit button invites a press that would
    # only report "still transcribing".
    mine = bool(active_target) and active_target == target
    shown = state if mine else STATE_IDLE

    # The live level and clock pick the frame. The painter on the other three
    # surfaces reads the same two numbers per redraw; here they are quantized
    # into a frame index because an icon is a fixed image.
    level = float(getattr(wm, "mixar_audio_level", 0.0) or 0.0)
    pulse = time.monotonic()
    icon_value = glyph_icons.icon_id(shown, level, pulse)

    row = layout.row(align=True)
    if icon_value:
        button = row.operator("mixar.voice_record_toggle", text="", icon_value=icon_value)
    else:
        button = row.operator(
            "mixar.voice_record_toggle",
            text="",
            icon=_FALLBACK_ICONS.get(shown, 'SOUND'),
            # `depress` only on the fallback: the rasterized recording frame
            # already carries the halo and the stop square, and a pressed-in
            # widget under it reads as a second, competing state.
            depress=mine and state == STATE_RECORDING,
        )
    button.target = target

    if not mine:
        return

    if state == STATE_RECORDING:
        _draw_clock(row, wm)
    elif state == STATE_TRANSCRIBING:
        row.label(text="Transcribing…")


def _draw_clock(row, wm) -> None:
    """Elapsed recording time beside the mic.

    The level itself is in the GLYPH now — the halo grows with it, exactly as
    on the other three surfaces — so the progress bar that used to stand in for
    it is gone. It was the one piece of this control that existed nowhere else,
    and it said the same thing twice once the halo arrived.

    The clock stays: the composer draws one too, and it is the only part of a
    recording a glyph cannot express.
    """
    duration = float(getattr(wm, "mixar_audio_duration", 0.0) or 0.0)
    remaining = max(0.0, MAX_RECORDING_SECONDS - duration)
    # Near the ceiling the clock counts DOWN: "4:58" says nothing useful, but
    # "10s left" says the recording is about to stop on its own.
    row.label(
        text=f"{int(remaining)}s left" if remaining <= 15.0 else _format_clock(duration)
    )


def draw_prompt_mic(header, context, prop_owner) -> None:
    """Add the mic to a boxed prompt's header row.

    The whole thing — the right-aligned sub-row, the missing-context case and
    the failure guard — lives here rather than in `draw_prompt_section`, so the
    shared helper gains one call and dictation stays this module's business.
    Never raises: dictation sits on top of a prompt that works without it, and
    a failure here must not blank the tab it decorates.
    """
    if context is None:
        return
    try:
        row = header.row(align=True)
        row.alignment = 'RIGHT'
        draw_mic_for_tab(row, context, prop_owner)
    except Exception:
        logger.debug("[Voice] prompt mic skipped", exc_info=True)


def draw_mic_for_tab(layout, context, prop_owner) -> None:
    """Draw the mic for a tab's prompt, addressed by its PropertyGroup.

    The owner's RNA identifier IS the target name — the same identifier
    `prompt_submit.PROMPT_TAB_DISPATCH` keys its Enter-to-generate table on —
    so a tab reachable by one is reachable by the other, and a tab that is in
    neither table simply gets no mic rather than a mic pointing nowhere.
    """
    try:
        owner_type = type(prop_owner).__name__
    except Exception:
        return
    target = target_for_tab(owner_type)

    from ..core.targets import is_valid_target

    if not is_valid_target(target):
        return
    draw_mic_button(layout, context, target)

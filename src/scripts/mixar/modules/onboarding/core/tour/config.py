# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — constants.

Kept out of ``onboarding/constants.py`` (already at the 500-line cap).
Everything about the video-narrated tour that is a tunable number or a
piece of copy lives here; the beat table itself is ``beats.py``.
"""

import os

# ---------------------------------------------------------------------------
# Assets — relative to ``onboarding/assets/``.
# ---------------------------------------------------------------------------
# The founder recording. Until it exists the build ships a generated
# placeholder with the same beat timestamps (scripts/dev/make_tour_placeholder.sh).
VIDEO_ASSET = "tour/founder.mp4"
VIDEO_PLACEHOLDER_ASSET = "tour/founder_placeholder.mp4"
DEMO_IMAGE_ASSET = "tour/demo_concept.png"

# Used only when the container's frame count / audio length can't be read.
VIDEO_FPS_FALLBACK = 24.0

# ---------------------------------------------------------------------------
# Operators / properties.
# ---------------------------------------------------------------------------
OP_TOUR = "mixar.onboarding_tour"
WM_PROP_TOUR_STATE = "mixar_tour_state"        # JSON, read by the QA harness
WM_PROP_TOUR_QA_TARGETS = "mixar_tour_qa_targets"  # JSON list of control rects

# Environment override so the QA harness can run the whole tour in a few
# seconds: playback rate multiplier applied to the clock at start.
ENV_CLOCK_RATE = "MIXAR_TOUR_CLOCK_RATE"
# Set to "1" to force the silent wall clock (no aud) — deterministic CI.
ENV_SILENT = "MIXAR_TOUR_SILENT"

# ---------------------------------------------------------------------------
# Timing.
# ---------------------------------------------------------------------------
TICK_SECONDS = 1.0 / 30.0
GATE_AUTO_ADVANCE_DEFAULT_MS = 10000
# After the terminal beat's clip end: the card fades out over the replay
# caption for this long before the modal ends.
END_AFTER_WALL_MS = 2500
SKIP_DWELL_MS = 500
# The terminal beat counts as reached this close to its clip end: an audio
# clock can settle a few ms short of the file's end and never cross it.
TERMINAL_END_SLACK_MS = 250
CLICK_PULSE_SECONDS = 0.6
CURSOR_GLIDE_RATE = 6.0          # exponential ease constant (1/s)
CURSOR_ORBIT_RADIUS = 46.0
CURSOR_ORBIT_SPEED = 1.6         # rad/s
SCRIBBLE_REVEAL_SECONDS = 0.45
CARD_FADE_SECONDS = 0.25         # card alpha 0 -> 1 on tour start
CARD_FADE_OUT_SECONDS = 0.6      # card alpha 1 -> 0 at the end (CardMotion.fade_out)
CARD_MOVE_RATE = 8.0             # exponential ease of the card rect (1/s)
CARD_MOVE_SNAP_PX = 0.5          # within this of the target the rect snaps
CONTROL_REVEAL_RATE = 10.0       # exponential ease of the controls strip (1/s)

SPEED_OPTIONS = (1.0, 1.25, 1.5, 2.0)

# ---------------------------------------------------------------------------
# Video card geometry (logical px, multiplied by the UI scale).
#
# The card is the video and nothing else: a dark rounded background only
# ``CARD_PAD`` larger than the frame, a hairline progress bar along the
# frame's bottom edge and the caption pill. The controls live in a
# translucent strip INSIDE the bottom of the video (``CARD_CONTROLS_H``)
# that is invisible until the pointer hovers the card, the tour is paused
# or the exit dialog is up.
# ---------------------------------------------------------------------------
# Two sizes only: "hero" for the framed intro/outro, "half" for every
# beat over the live UI (the old 300 px "card" read as a thumbnail).
CARD_VARIANTS = {
    "hero": 560,
    "half": 400,
}
CARD_ASPECT = 16.0 / 9.0
CARD_MARGIN = 28
CARD_CONTROLS_H = 28             # inner controls strip, bottom of the video
# Keep CARD_RADIUS <= 2.8 * CARD_PAD: the video quad has square corners
# and must stay inside the rounded background's corner arcs.
CARD_RADIUS = 5
CARD_PAD = 2
CARD_PROGRESS_H = 2
CARD_BG = (0.09, 0.09, 0.11, 0.96)
CARD_PROGRESS_BG = (1.0, 1.0, 1.0, 0.12)
CARD_PROGRESS_FG = (0.205, 0.780, 0.430, 0.95)   # MIXAR_BRAND_GREEN
CONTROLS_FILM = (0.0, 0.0, 0.0, 0.62)          # strip film at full reveal
CONTROLS_FILM_BANDS = 4                        # stacked bands faking a gradient
CONTROL_TEXT = (0.92, 0.92, 0.94, 0.95)
CONTROL_TEXT_DIM = (0.65, 0.66, 0.70, 0.9)
CONTROL_FONT_PX = 13
CONTROL_GAP = 14
GATE_CAPTION_ALPHA_FLOOR = 0.6                 # always readable while gated
# Freeze-frame film over the paused video while a gate waits (times the
# session's eased 0..1 `gate_film`), so the pause reads as intentional.
GATE_FILM_ALPHA = 0.15
CAPTION_UNDER_GAP = 12                         # px between the card and a caption under it
PAUSED_DISC = (0.0, 0.0, 0.0, 0.45)
PAUSED_GLYPH = (1.0, 1.0, 1.0, 0.85)
PAUSED_DISC_RADIUS = 26

# ---------------------------------------------------------------------------
# Overlays.
# ---------------------------------------------------------------------------
# Rings, cursor pulses, the Continue pill: the Mixar brand green
# (MIXAR_BRAND_GREEN in common/notifications/constants.py; copied so this
# module stays import-light), not the theme's own yellow.
ACCENT = (0.205, 0.780, 0.430, 1.0)
SCRIBBLE_PAD = 8
SCRIBBLE_THICKNESS = 3.0
SCRIBBLE_RADIUS = 10.0
HINT_FONT_PX = 15
HINT_BG = (0.09, 0.09, 0.11, 0.92)
HINT_TEXT = (0.95, 0.95, 0.97, 1.0)
# Callout box (a beat that introduces something to act on later, e.g. the
# Creator Program row of the open Help menu).
CALLOUT_TITLE_PX = 17
CALLOUT_BODY_PX = 14
CALLOUT_BG = (0.07, 0.07, 0.09, 0.96)
# Shortcut panel (keycaps that light as the narration names them).
KEYS_TITLE_PX = 13
KEYS_CAP_PX = 13
KEYS_LABEL_PX = 15
KEYS_CAP_BG = (0.16, 0.16, 0.19, 1.0)
KEYS_CAP_EDGE = (1.0, 1.0, 1.0, 0.22)
HERO_DIM = (0.0, 0.0, 0.0, 0.82)
# "Your turn": while a beat waits on the user, the main window dims with a
# spotlight cut around the target, the ring pulses and the starburst shows.
# Automatic beats stay undimmed and calm so the two modes never look alike.
GATE_DIM = (0.0, 0.0, 0.0, 0.62)
SPOTLIGHT_PAD = 14               # logical px of bright margin around the target
GATE_RING_PULSE_SECONDS = 1.6    # breathing period of a gated ring
GATE_RING_PULSE_MIN = 0.55       # alpha floor of the breath
OVERLAY_FADE_SECONDS = 0.25      # rings/hints fade out instead of vanishing
GATE_DONE_FLASH_SECONDS = 0.6    # expanding ring when the user completes a gate
GATE_DONE_FLASH_GROW = 22        # logical px the flash ring grows outward

# ---------------------------------------------------------------------------
# Copy.
# ---------------------------------------------------------------------------
EXIT_CONFIRM_TITLE = "Leave the tour?"
EXIT_CONFIRM_BODY = "Two minutes now saves an hour of hunting later."
EXIT_CONFIRM_CONTINUE = "Continue tour"
EXIT_CONFIRM_QUIT = "Leave"
CONTROL_PAUSE = "Pause"
CONTROL_RESUME = "Play"
CONTROL_SKIP = "Next"
CONTROL_EXIT = "Exit"
HELP_MENU_START_TOUR = "Start tour"


def assets_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    # core/tour → ../../assets
    return os.path.normpath(os.path.join(here, "..", "..", "assets"))


def video_path() -> str:
    """The founder recording if present, else the placeholder, else ''."""
    for rel in (VIDEO_ASSET, VIDEO_PLACEHOLDER_ASSET):
        path = os.path.join(assets_dir(), rel)
        if os.path.isfile(path):
            return path
    return ""


def demo_image_path() -> str:
    return os.path.join(assets_dir(), DEMO_IMAGE_ASSET)

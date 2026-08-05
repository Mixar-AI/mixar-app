# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the sparse camera-directing workflow."""

DIRECTOR_CAMERA_BASENAME = "Mixar Shot Camera"
DIRECTOR_SHOT_BASENAME = "Shot"
DIRECTOR_TEXT_SUFFIX = ".camera.json"

DEFAULT_BEAT_SECONDS = 1.0
MIN_BEAT_SECONDS = 0.1
MAX_BEAT_SECONDS = 10.0

LENS_PRESETS_MM = (18, 24, 35, 50, 85)

# Width and height are deliberately modest. They establish the native scene
# aspect without silently opting the user into a heavyweight final render.
ASPECT_PRESETS = {
    "WIDE": ("16:9", 1920, 1080),
    "VERTICAL": ("9:16", 1080, 1920),
    "SQUARE": ("1:1", 1080, 1080),
}

DEFAULT_DIRECTION_PROMPT = (
    "Follow the selected camera beats in chronological order as the intended "
    "camera path."
)

SHOT_STATE_ITEMS = (
    (
        "DRAFT",
        "Draft",
        "The camera and timing remain editable",
        "UNLOCKED",
        0,
    ),
    (
        "LOCKED",
        "Locked",
        "The compiled sparse guidance is frozen for this take",
        "LOCKED",
        1,
    ),
)

GUIDANCE_STRENGTH_ITEMS = (
    ("CONSERVATIVE", "Conservative", "Stay close to the directed frames", 0),
    ("BALANCED", "Balanced", "Balance adherence with natural motion", 1),
    ("EXPRESSIVE", "Expressive", "Allow more interpretation between beats", 2),
)

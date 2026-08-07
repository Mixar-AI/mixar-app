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

# Familiar photographic focal lengths; directors think in millimetres, so
# the surface never presents field-of-view degrees.
LENS_PRESET_ITEMS = (
    (18, "Ultra Wide"),
    (24, "Wide"),
    (35, "Classic"),
    (50, "Standard"),
    (85, "Portrait"),
    (135, "Telephoto"),
)

LENS_PRESETS_MM = tuple(mm for mm, _label in LENS_PRESET_ITEMS)

LENS_TYPE_ITEMS = (
    ("PERSP", "Perspective", "Natural photographic lens projection", 0),
    ("ORTHO", "Orthographic", "Parallel projection without perspective", 1),
    ("PANO", "Panoramic", "Wraparound panoramic projection", 2),
)

# Width and height are deliberately modest. They establish the native scene
# aspect without silently opting the user into a heavyweight final render.
ASPECT_PRESETS = {
    "PHOTO": ("Photography / DSLR · 3:2", 1620, 1080),
    "SMARTPHONE": ("Smartphones · 4:3", 1440, 1080),
    "WIDE": ("Video / TV · 16:9", 1920, 1080),
    "CINEMA_185": ("Cinema · 1.85:1", 1998, 1080),
    "CINEMA_239": ("Cinema · 2.39:1", 2390, 1000),
    "VERTICAL": ("Social media · 9:16", 1080, 1920),
    "SQUARE": ("Square · 1:1", 1080, 1080),
}

DEFAULT_DIRECTION_PROMPT = (
    "Follow the selected keyframes in chronological order as the intended "
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
    ("EXPRESSIVE", "Expressive", "Allow more interpretation between keyframes", 2),
)

SHOT_RENDER_OUTPUT_ITEMS = (
    (
        "BEAUTY",
        "Beauty Preview",
        "Material-color preview with studio lighting",
        1,
    ),
    (
        "CLAY",
        "Clay",
        "Neutral clay preview that emphasizes shape and motion",
        2,
    ),
    (
        "DEPTH",
        "Depth",
        "Normalized camera-depth guide with near geometry shown brighter",
        4,
    ),
)

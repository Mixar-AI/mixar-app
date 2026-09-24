# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the sparse camera-directing workflow."""

DIRECTOR_CAMERA_BASENAME = "Mixar Shot Camera"
DIRECTOR_SHOT_BASENAME = "Shot"
DIRECTOR_TEXT_SUFFIX = ".camera.json"

# Native dense motion samples stay out of the sparse beat strip.
RECORDED_KEY_TYPE = 'JITTER'

DEFAULT_BEAT_SECONDS = 1.0
MIN_BEAT_SECONDS = 0.1
MAX_BEAT_SECONDS = 10.0

# The Cinema Mode Speed slider retimes the ACTIVE SHOT: every interval between
# its keyframes is scaled by ``2 ** (-speed)``, so +1 plays twice as fast, -1
# half as fast, and the slider rests in the middle at the timing as captured.
# (``beat_seconds`` above stays the spacing for future captures.)
SPEED_MIN = -1.0
SPEED_MAX = 1.0
DEFAULT_SPEED = 0.0

# Familiar photographic focal lengths; directors think in millimetres, so the
# surface never presents field-of-view degrees — and it names a focal length by
# its focal length. A descriptive word in front of it is the same number plus
# the arguable half, since 35mm reads as normal to one director and wide to
# another.
LENS_PRESETS_MM = (18, 24, 35, 50, 85, 135)

# The focal-length slider's TRAVEL. Blender's own soft range on `Camera.lens`
# is 1-5000mm, which puts the whole usable photographic range inside the first
# few pixels of the drag — "drastically high and sensitive". Text entry still
# reaches the hard range, so nothing is lost by making the drag usable.
LENS_SLIDER_MIN_MM = 10.0
LENS_SLIDER_MAX_MM = 300.0

# Same for an orthographic camera's scale, which IS its framing: a slider's
# drag rate is its range spread over the row's width, so the stock soft range
# (to 1000) and even 100 moved the frame by half a metre per pixel. 20 covers
# the framing anyone reaches for; text entry still reaches the hard range.
ORTHO_SCALE_SLIDER_MIN = 0.1
ORTHO_SCALE_SLIDER_MAX = 20.0

# Depth of field. `aperture_fstop` ships a 0-infinity hard range with a soft
# range that runs far past any lens anyone has held; f/0.95 to f/22 is the
# photographic span, so that is the drag. Text entry still reaches the rest.
FSTOP_SLIDER_MIN = 0.95
FSTOP_SLIDER_MAX = 22.0

# The stops a director asks for by name. Whole stops from wide open, so the
# row reads like a lens barrel rather than a slider readout.
FSTOP_PRESETS = (1.4, 2.0, 2.8, 4.0, 5.6, 8.0)

LENS_TYPE_ITEMS = (
    ("PERSP", "Perspective", "Natural photographic lens projection", 0),
    ("ORTHO", "Orthographic", "Parallel projection without perspective", 1),
    ("PANO", "Panoramic", "Wraparound panoramic projection", 2),
)

# Aspect ratios, named by their RATIO and nothing else. A director reads
# "2.39:1"; a medium name in front of it is the same information plus a claim
# the ratios did not support — two of the old labels named one medium at two
# different ratios.
#
# The value is the RATIO, not a pixel size. Pixel sizes made aspect and
# resolution fight: picking 2.39:1 wrote 2390x1000, whose short side matched no
# tier, so the resolution segment lit nothing. Applying a ratio keeps the
# scene's current short side, so the two settings are orthogonal.
ASPECT_PRESETS = {
    "PHOTO": ("3:2", 3, 2),
    "SMARTPHONE": ("4:3", 4, 3),
    "WIDE": ("16:9", 16, 9),
    "CINEMA_185": ("1.85:1", 185, 100),
    "CINEMA_239": ("2.39:1", 239, 100),
    "VERTICAL": ("9:16", 9, 16),
    "SQUARE": ("1:1", 1, 1),
}

# Camera "template styles" — the design's named list of how a shot moves.
#
# Two of these are STATES that stay live on the shot (handheld drift, a
# levelled horizon) and two are one-shot MOVES that key a path. They share a
# list because the user thinks of them as one choice, but the underlying
# contract is untouched: handheld remains an F-modifier flag and never
# becomes a camera-move preset (see `core/handheld.py`).
CAMERA_TEMPLATE_ITEMS = (
    ("NONE", "None", "Plain camera; no drift and no preset motion", 0),
    (
        "HANDHELD",
        "Handheld camera",
        "Add organic handheld drift on top of the captured path",
        1,
    ),
    (
        "Z_FIXED",
        "Z-Fixed",
        "Keep the horizon level; roll is removed as the camera moves",
        2,
    ),
    ("DOLLY_ZOOM", "Dolly Zoom", "Key a push toward the subject", 3),
    ("CRANE", "Crane", "Key a rise above the subject", 4),
)

# Quality tiers for the shot's output. The preset sets the SHORTER side, so a
# vertical 9:16 scene reads 1080p as 1080x1920 — the same tier, not a
# quarter-resolution surprise.
RESOLUTION_PRESETS = {
    "HD720": ("720p", 720),
    "HD1080": ("1080p", 1080),
    "K2": ("2K", 1440),
    "K4": ("4K", 2160),
}

RESOLUTION_PRESET_ITEMS = tuple(
    (key, label, f"Render at {label}", index)
    for index, (key, (label, _short)) in enumerate(RESOLUTION_PRESETS.items())
)

DEFAULT_DIRECTION_PROMPT = (
    "Follow the selected keyframes in chronological order as the intended "
    "camera path."
)

# Blender's own keyframe interpolation types, in its order. The identifiers
# are `KeyframePoint.interpolation` values and are written straight to the
# keys, so this list must stay a subset of what the running Blender accepts.
INTERPOLATION_ITEMS = (
    ("CONSTANT", "Constant", "No interpolation, hold each keyframe", 0),
    ("LINEAR", "Linear", "Straight-line interpolation", 1),
    ("BEZIER", "Bezier", "Smooth interpolation between keyframes", 2),
    ("SINE", "Sinusoidal", "Sinusoidal easing (weakest, almost linear)", 3),
    ("QUAD", "Quadratic", "Quadratic easing", 4),
    ("CUBIC", "Cubic", "Cubic easing", 5),
    ("QUART", "Quartic", "Quartic easing", 6),
    ("QUINT", "Quintic", "Quintic easing", 7),
    ("EXPO", "Exponential", "Exponential easing (dramatic)", 8),
    ("CIRC", "Circular", "Circular easing (strongest and most dynamic)", 9),
    ("BACK", "Back", "Cubic easing with overshoot and settle", 10),
    ("BOUNCE", "Bounce", "Exponentially decaying parabolic bounce", 11),
    ("ELASTIC", "Elastic", "Exponentially decaying sine wave", 12),
)

# The SAME list a beat can choose from, plus the row that says "whatever the
# shot says". A keyframe's interpolation governs the segment FROM it TO the
# next one, which is exactly what "the easing between these two keyframes"
# means — so an override lives on the earlier keyframe of the pair. Beats rest
# on SHOT so a take still eases one way by default and nothing has to be set
# per keyframe to get the old behaviour back.
BEAT_INTERPOLATION_DEFAULT = "SHOT"
BEAT_INTERPOLATION_ITEMS = (
    (
        BEAT_INTERPOLATION_DEFAULT,
        "Shot Default",
        "Ease the way the rest of the shot does",
        100,
    ),
) + INTERPOLATION_ITEMS

# Name of the Track To constraint Director owns on a tracking shot camera.
TRACK_CONSTRAINT_NAME = "Mixar Director Track"

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

# The three videos Export to Moodboard renders. Named for what each LOOKS
# like — "Beauty Preview" is compositing jargon, and "guides" said nothing
# about what arrives on the board.
SHOT_RENDER_OUTPUT_ITEMS = (
    (
        "BEAUTY",
        "Color",
        "The scene's own materials under studio lighting",
        1,
    ),
    (
        "CLAY",
        "Clay",
        "Plain gray surfaces, so shape and motion read on their own",
        2,
    ),
    (
        "DEPTH",
        "Depth",
        "A depth map: nearer surfaces brighter",
        4,
    ),
)

# Video size presets, as percentages of the scene's output size. The popup
# shows them as three cells and states the pixel size they make; the native
# copy in `view3d_director_popup_render.cc` must match.
VIDEO_SIZE_PRESETS = (
    (25, "Draft", "A quarter of the output size: fastest"),
    (50, "Half", "Half the output size"),
    (100, "Full", "The full output size: slowest"),
)


# Where the camera-first "Export to Moodboard" surface takes its render span
# from. Director shots always render their beat span; a power user animating a
# camera natively expects the scene or preview range they already work in.
CAMERA_EXPORT_RANGE_ITEMS = (
    (
        "CAMERA_KEYS",
        "Camera Keys",
        "First to last keyframe on the chosen camera",
        0,
    ),
    (
        "SCENE",
        "Scene Range",
        "The scene's own Start and End frames",
        1,
    ),
    (
        "PREVIEW",
        "Preview Range",
        "The scene's preview range, or its frame range when none is set",
        2,
    ),
)

# One label, one panel id: the Render menu row, the animation-editor row and
# the popup they both open must name the same thing.
CAMERA_EXPORT_LABEL = "Export to Moodboard"
CAMERA_EXPORT_PANEL_ID = "MIXAR_PT_camera_export"

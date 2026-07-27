# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Module Constants

Centralized configuration values for the moodboard module.
"""

# ============================================================================
# JOB QUEUE IDENTIFIERS
# ============================================================================

SCENE_GEN_CAPABILITY_KEY = "scene_gen"
SCENE_GEN_JOB_TYPE = SCENE_GEN_CAPABILITY_KEY
SCENE_GEN_MODEL = "scene_gen_v1"

# ============================================================================
# TURNAROUND / MULTI-VIEW DETECTION
# ============================================================================

# Sentinel for "this moodboard image is not a labelled turnaround panel".
TURNAROUND_VIEW_NONE = 'none'

# The primary view. Its S3 key goes into the job payload's ``image_s3_key``;
# it must NEVER appear in ``multi_view_images`` (the vendor's multi-view enum
# has no ``front`` member and rejects the payload).
TURNAROUND_VIEW_FRONT = 'front'

# View types accepted by the backend's /model-3d/detect-views response and by
# the Hunyuan Pro multi-view payload. Order drives the sidebar dropdown; left
# and right lead because they are the labels users most often need to correct.
TURNAROUND_VIEW_TYPES = (
    (TURNAROUND_VIEW_NONE, "None", "Not part of a detected turnaround"),
    (TURNAROUND_VIEW_FRONT, "Front", "Primary view (sent as the main image)"),
    ('left', "Left", "Left side view"),
    ('right', "Right", "Right side view"),
    ('back', "Back", "Rear view"),
    ('top', "Top", "Top-down view"),
    ('bottom', "Bottom", "Bottom-up view"),
    ('left_front', "Left Front", "Three-quarter view from the left"),
    ('right_front', "Right Front", "Three-quarter view from the right"),
)

# Models known to accept multi-view input, used ONLY when the generation
# catalog has not populated the per-model ``supports_multi_view`` flag
# (offline / pre-auth). Prefer generation_params.model_supports_multi_view().
# TODO: drop this list once every multi-view model in the catalog carries
# supports_multi_view=True.
TURNAROUND_FALLBACK_MULTI_VIEW_SLUGS = (
    "hunyuan_pro_v3.1",
    "hunyuan_pro_v3",
    "hunyuan_pro_v2.5",
)

# ============================================================================
# IMAGE EDITING CONSTANTS
# ============================================================================

# Image display size (must match C++ MOODBOARD_IMAGE_BASE_SIZE)
MOODBOARD_IMAGE_BASE_SIZE = 700.0

# Horizontal offset between original and masked image
MOODBOARD_IMAGE_SPACING = 50.0

# Horizontal gap between multiple images added at once
MOODBOARD_MULTI_IMAGE_GAP = 50.0

# Maximum number of concentric rings searched when looking for a free slot to
# drop a newly added image so it does not overlap existing moodboard images.
MOODBOARD_MAX_PLACEMENT_RING = 16

# ============================================================================
# IMAGE PROPERTY DEFAULTS
# ============================================================================

IMAGE_POSITION_X_DEFAULT = 0.0
IMAGE_POSITION_Y_DEFAULT = 0.0
IMAGE_SCALE_DEFAULT = 1.0
IMAGE_SCALE_MIN = 0.1
IMAGE_SCALE_MAX = 50.0
IMAGE_Z_ORDER_DEFAULT = 0
IMAGE_ROTATION_DEFAULT = 0.0
IMAGE_ROTATION_MIN = -360.0
IMAGE_ROTATION_MAX = 360.0
IMAGE_FLIP_HORIZONTAL_DEFAULT = False
IMAGE_FLIP_VERTICAL_DEFAULT = False
IMAGE_SELECTED_DEFAULT = False

# ============================================================================
# TEXTBOX PROPERTY DEFAULTS
# ============================================================================

TEXTBOX_TEXT_DEFAULT = "Text"
TEXTBOX_POSITION_X_DEFAULT = 0.0
TEXTBOX_POSITION_Y_DEFAULT = 0.0
TEXTBOX_FONT_SIZE_DEFAULT = 48
TEXTBOX_FONT_SIZE_MIN = 8
TEXTBOX_FONT_SIZE_MAX = 500
TEXTBOX_COLOR_DEFAULT = (1.0, 1.0, 1.0, 1.0)
TEXTBOX_BACKGROUND_COLOR_DEFAULT = (0.0, 0.0, 0.0, 0.0)
TEXTBOX_WIDTH_DEFAULT = 400.0
TEXTBOX_WIDTH_MIN = 50.0
TEXTBOX_WIDTH_MAX = 2000.0
TEXTBOX_HEIGHT_DEFAULT = 100.0
TEXTBOX_HEIGHT_MIN = 30.0
TEXTBOX_HEIGHT_MAX = 2000.0
TEXTBOX_ROTATION_DEFAULT = 0.0
TEXTBOX_ROTATION_MIN = -360.0
TEXTBOX_ROTATION_MAX = 360.0
TEXTBOX_Z_ORDER_DEFAULT = 0

# ============================================================================
# SCENE PROPERTY DEFAULTS
# ============================================================================

MOODBOARD_SELECTED_INDEX_DEFAULT = -1
MOODBOARD_PROMPT_DEFAULT = ""
MOODBOARD_GLOBAL_CONTEXT_DEFAULT = ""
MOODBOARD_USE_STYLE_CONTEXT_DEFAULT = True
MOODBOARD_GEMINI_MODEL_DEFAULT = 'gemini-2.5-flash-image'
MOODBOARD_ASPECT_RATIO_DEFAULT = '16:9'

# ============================================================================
# ENUM VALUES
# ============================================================================

GEMINI_MODELS = [
    ('gemini-2.5-flash-image', "Flash (Fast)", "Faster generation, 1024px resolution"),
    ('gemini-3-pro-image-preview', "Pro (Quality)", "Higher quality, up to 4K resolution")
]

ASPECT_RATIOS = [
    ('1:1', "1:1 Square", "Square aspect ratio"),
    ('16:9', "16:9 Wide", "Widescreen aspect ratio"),
    ('9:16', "9:16 Portrait", "Portrait aspect ratio"),
    ('4:3', "4:3", "Standard aspect ratio"),
    ('3:4', "3:4", "Portrait aspect ratio"),
    ('21:9', "21:9 Ultrawide", "Ultra-wide aspect ratio")
]

TEXT_ALIGNMENTS = [
    ('LEFT', "Left", "Align text to the left"),
    ('CENTER', "Center", "Center text"),
    ('RIGHT', "Right", "Align text to the right")
]

EDIT_TOOL_TYPES = [
    ('NONE', "None", "No tool active"),
    ('CROP', "Crop", "Crop tool"),
    ('BOX_MASK', "Box Mask", "Box mask selection"),
    ('LASSO', "Lasso", "Lasso selection"),
    ('MAGIC_SELECT', "Magic Select", "AI-powered object selection"),
]

# ============================================================================
# TOOL SETTINGS
# ============================================================================

# Lasso tool minimum distance between points (in normalized 0-1 space)
LASSO_MIN_DISTANCE_THRESHOLD = 0.0001

# Lasso tool minimum number of points required for mask
LASSO_MIN_POINTS = 3

# Warning threshold for reference image count
REFERENCE_IMAGES_MAX_WITH_WARNING = 14

# ============================================================================
# GROUP DRAWING CONSTANTS (used by mixie_draw_moodboard_groups.cc)
# ============================================================================

# Size of group selection handles in pixels
GROUP_HANDLE_SIZE_PX = 12.0

# Default group selection color (RGBA)
GROUP_SELECTION_COLOR = (0.2, 0.6, 1.0, 1.0)

# ============================================================================
# SIDEBAR LAYOUT CONSTANTS (must match C++ constants)
# ============================================================================

# Sidebar dimensions
SIDEBAR_WIDTH_DEFAULT = 320
SIDEBAR_MIN_WIDTH = 240
SIDEBAR_MAX_WIDTH = 600
SIDEBAR_PADDING = 12
SIDEBAR_SECTION_SPACING = 16
SIDEBAR_ELEMENT_SPACING = 8

# UI element sizes
SIDEBAR_BUTTON_HEIGHT = 36
SIDEBAR_GENERATE_BUTTON_HEIGHT = 48
IMAGE_TYPE_BUTTON_SIZE = 80
IMAGE_TYPE_GRID_COLUMNS = 2
UPLOAD_ZONE_HEIGHT = 120
MODEL_TYPE_BUTTON_WIDTH = 140
POSE_BUTTON_SIZE = 60
LICENSE_BUTTON_WIDTH = 140

# Header
HEADER_HEIGHT = 48
HEADER_ICON_SIZE = 24

# Cost indicator
COST_INDICATOR_HEIGHT = 32
COST_INDICATOR_ICON_SIZE = 16

# Generate button scale factor (used in popup draw methods)
GENERATE_BUTTON_SCALE_Y = 1.4

# Sidebar Python UI spacing tokens
SEP_SECTION = 0.8     # Between major sections
SEP_INTRA   = 0.15    # Between elements inside a box
SEP_FOOTER  = 1.0     # Before the generate button
HINT_SCALE_Y = 0.85   # Subtle info/constraint labels

# Colors (RGBA tuples)
SIDEBAR_UPLOAD_ZONE_BORDER = (0.5, 0.5, 0.5, 0.5)
SIDEBAR_GENERATE_BUTTON_BG = (0.6, 0.8, 0.3, 1.0)  # Green
SIDEBAR_GENERATE_BUTTON_HOVER = (0.7, 0.9, 0.4, 1.0)

# ============================================================================
# SCENE ASSET FILLER CONSTANTS
# ============================================================================

# Minimum similarity score to accept an asset library match
MIN_SIMILARITY_SCORE = 0.3

# Maximum number of prompts per batch search request
BATCH_SEARCH_CHUNK_SIZE = 20

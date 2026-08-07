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
# NOTE: the model slug is deliberately NOT a constant here. Model rows are
# server-owned and change without a client release, so the submit path reads
# the service's default from the generation catalog
# (``generation_params.catalog_default_model``) and aborts when the catalog
# cannot answer.

# ============================================================================
# TURNAROUND / MULTI-VIEW DETECTION
# ============================================================================

# The multi-view set holds COMPANIONS ONLY. The main image is the Model Gen
# tab's Input Image and is never a member of the group — so there is no
# 'main', 'front' or 'none' label here. The seven ids below are exactly the
# vendor's ``ViewType`` enum (backend modules/hunyuan/schemas/requests.py);
# Hunyuan Pro takes 1 frontal image + these 7 angles, 8 images maximum.
TURNAROUND_VIEW_TYPES = (
    ('left', "Left", "Left side view"),
    ('right', "Right", "Right side view"),
    ('back', "Back", "Rear view"),
    ('top', "Top", "Top-down view"),
    ('bottom', "Bottom", "Bottom-up view"),
    ('left_front', "Left Front", "Three-quarter view from the left"),
    ('right_front', "Right Front", "Three-quarter view from the right"),
)

# Assignment order for "Add Selected" — the next unused angle is handed out
# from this sequence, so the common left/right/back turnaround needs no
# dropdown fiddling at all.
TURNAROUND_VIEW_ORDER = tuple(item[0] for item in TURNAROUND_VIEW_TYPES)

# Label a detached image falls back to. Meaningless on its own: membership is
# ``turnaround_group != ""``, never the view type.
TURNAROUND_VIEW_DEFAULT = TURNAROUND_VIEW_ORDER[0]

# Vendor cap: 1 frontal + 7 angles. The Input Image is the frontal one, so the
# group itself tops out at seven companions.
TURNAROUND_MAX_COMPANIONS = len(TURNAROUND_VIEW_ORDER)


# ---------------------------------------------------------------------------
# detect-views response vocabulary (NOT view_type labels)
# ---------------------------------------------------------------------------

# ``panels[0].view_type`` is always this: the sheet's front orthographic,
# falling back to its hero render when the sheet has no front. It becomes the
# tab's Input Image — never a group member.
DETECT_PANEL_MAIN = 'main'

# Returned only when the sheet has BOTH a front and a hero render. No vendor
# ``ViewType`` describes it, so it is not a companion either: it lands on the
# moodboard untagged next to the main, as an alternative Input Image for
# stylised sheets that reconstruct badly from the flat front.
DETECT_PANEL_HERO = 'hero'

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
MOODBOARD_ASPECT_RATIO_DEFAULT = '16:9'

# ============================================================================
# ENUM VALUES
# ============================================================================

# NOTE: there is deliberately no GEMINI_MODELS list here. The image_gen models
# are catalog rows served under the catalog's OWN slugs ('pro', 'flash-3-1'),
# not raw vendor ids — keeping a second vocabulary client-side is how the two
# drifted apart. The Model dropdown builds its items from
# ``generation_catalog_cache.get_model_enum_items('image_gen')``.

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

# ============================================================================
# MOODBOARD GRAPH STRING LENGTH CONTRACT
# ============================================================================

# Frozen contract with the C++ canvas. Every value below MUST stay strictly
# smaller than the fixed stack buffer the corresponding ``RNA_string_get`` call
# writes into, mirroring the existing moodboard textbox pairing
# (``maxlen=2048`` <-> ``char text_buffer[4096]``). Without a ``maxlen`` an RNA
# string is unbounded and ``RNA_string_get`` is strcpy-shaped, so a long value —
# a catalog-published ``label``, or ``object_names`` written by an agent script —
# smashes the stack during draw. The C++ side additionally clamps on read
# (``mixie_rna_string_get_clamped``), because ``maxlen`` is only enforced on
# assignment and a .blend saved by an older build can still carry a longer value.
GRAPH_NODE_ID_MAXLEN = 64          # <-> char node_id[128]
GRAPH_SOCKET_ID_MAXLEN = 96        # <-> char socket_id[128] / to_socket[128]
GRAPH_ACCEPTED_TYPES_MAXLEN = 96
GRAPH_SERVICE_KEY_MAXLEN = 96
GRAPH_MODEL_SLUG_MAXLEN = 128
GRAPH_LABEL_MAXLEN = 192           # <-> char label[256] / title[256]
GRAPH_DESCRIPTION_MAXLEN = 512
GRAPH_WIDGET_MAXLEN = 48           # <-> char widget[64]
GRAPH_OBJECT_NAMES_MAXLEN = 2048   # <-> char names[4096]
GRAPH_JOB_ID_MAXLEN = 128
GRAPH_ERROR_MAXLEN = 512
GRAPH_PARAM_NAME_MAXLEN = 96

# ============================================================================
# VIDEO NODE OUTPUT DURATION
# ============================================================================

# Catalog parameter carrying a video model's OUTPUT length in seconds. Keyed by
# name, which is a KNOWN CATALOG GAP: parameter schemas publish type/bounds/
# widget but nothing that identifies a parameter's MEANING, and "make the output
# as long as the input" is inherently semantic. Every other consumer of the
# schema is name-agnostic on purpose (key sets change from the DB without a
# client release), so this is the one place a name is assumed — and it fails
# soft: a model that renames or omits the parameter simply keeps the catalog
# default instead of being seeded. Retire it by publishing a role/semantic hint
# on the parameter (e.g. `"role": "output_duration"`) and matching on that.
VIDEO_DURATION_PARAM_NAME = "duration"

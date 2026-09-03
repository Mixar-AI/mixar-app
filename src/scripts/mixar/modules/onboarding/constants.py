# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Constants

All step IDs, copy strings, and operator names live here. The
flow is purely informational — five short cards that explain
Mixar's core features (moodboard, image generation, image-to-3D,
retopology, Mixie Chat) bracketed by a welcome and a completion
screen. No prompt pre-fills, no pollers, no auto-action.
"""

# ---------------------------------------------------------------------------
# Feature flag — dev override that fires the welcome on every Blender
# launch regardless of auth state. In production the welcome is
# triggered solely from the auth-success hook the first time a user
# signs in (see ``onboarding.core.maybe_show_for_user`` and
# ``auth_hooks.maybe_show_onboarding``); a per-user "seen" file in
# ``~/.mixar/onboarding_seen.json`` dedupes subsequent boots.
ONBOARDING_DEV_ALWAYS_ON = False

# ---------------------------------------------------------------------------
# Trigger timings.
# ---------------------------------------------------------------------------

# Grace period after Blender's user-driven load_post before the
# welcome dialog appears.
WELCOME_POST_LOAD_DELAY_SECONDS = 0.2

# Fallback delay for the splash-disabled / Esc-dismissed paths.
# In the new UI the splash + agent bubble auto-dismiss reasonably
# quickly, so we don't need the original 15s buffer — 3s is enough
# for the splash to be gone but short enough that the user doesn't
# feel the tour is "stuck".
WELCOME_FALLBACK_DELAY_SECONDS = 3.0

# How long we wait between advancing tour state (in execute) and
# Blender being done dismissing the previous popup. One tick is
# enough; longer feels sluggish.
STEP_ADVANCE_DEFER_SECONDS = 0.05

# ---------------------------------------------------------------------------
# Step IDs. Persisted as plain strings on a WindowManager StringProperty.
# ---------------------------------------------------------------------------
STEP_WELCOME = "WELCOME"
STEP_INFO_MOODBOARD = "INFO_MOODBOARD"
STEP_INFO_IMAGEGEN = "INFO_IMAGEGEN"
STEP_INFO_IMAGE_TO_3D = "INFO_IMAGE_TO_3D"
STEP_INFO_RETOPOLOGY = "INFO_RETOPOLOGY"
STEP_INFO_MIXIE_CHAT = "INFO_MIXIE_CHAT"
STEP_INFO_ENGINE_MODE = "INFO_ENGINE_MODE"
# Second-to-last card: offer to bring the user's existing Blender
# add-ons across. The two outcome cards below are reached only from
# this card's Import button, so they carry no step dots of their own.
STEP_PLUGIN_IMPORT = "PLUGIN_IMPORT"
STEP_PLUGIN_IMPORT_NONE = "PLUGIN_IMPORT_NONE"
STEP_PLUGIN_IMPORT_DONE = "PLUGIN_IMPORT_DONE"
STEP_COMPLETION = "COMPLETION"
STEP_DONE = "DONE"

DEFAULT_STEP = STEP_WELCOME

# Total info-step count, used in the "STEP N OF M" badges.
TOTAL_INFO_STEPS = 7

# ---------------------------------------------------------------------------
# Sidebar category names — offline FALLBACK labels only. The moodboard
# panels' bl_category values are catalog-driven now, so the tour driver
# resolves these through moodboard_sidebar_panels.get_tab_category()
# (capability key → current label) before switching the sidebar.
# ---------------------------------------------------------------------------
CATEGORY_IMAGE_GEN = "Image Gen"
CATEGORY_IMAGE_TO_3D = "Model Gen"
CATEGORY_RETOPOLOGY = "Retopology"

# ---------------------------------------------------------------------------
# WindowManager property names.
# ---------------------------------------------------------------------------
WM_PROP_STEP = "mixar_onboarding_step"
WM_PROP_OPTED_OUT = "mixar_onboarding_opted_out"

# ---------------------------------------------------------------------------
# Operator IDs.
# ---------------------------------------------------------------------------
OP_WELCOME = "mixar.onboarding_welcome"
OP_PICK_SKIP = "mixar.onboarding_pick_skip"
OP_ADVANCE = "mixar.onboarding_advance"
OP_SKIP_TOUR = "mixar.onboarding_skip_tour"
OP_RESTART = "mixar.onboarding_restart"
OP_COMPLETION = "mixar.onboarding_completion"

# Per-step info dialog ops.
OP_STEP_INFO_MOODBOARD = "mixar.onboarding_info_moodboard"
OP_STEP_INFO_IMAGEGEN = "mixar.onboarding_info_imagegen"
OP_STEP_INFO_IMAGE_TO_3D = "mixar.onboarding_info_image_to_3d"
OP_STEP_INFO_RETOPOLOGY = "mixar.onboarding_info_retopology"
OP_STEP_INFO_MIXIE_CHAT = "mixar.onboarding_info_mixie_chat"
OP_STEP_INFO_ENGINE_MODE = "mixar.onboarding_info_engine_mode"

# ---------------------------------------------------------------------------
# Background dim film — semi-transparent black drawn behind the
# floating dialogs to make them stand out.
# ---------------------------------------------------------------------------
# Dim film opacity. Dropped from 0.82 → 0.62 so the editor underneath
# stays clearly visible — the screen reads as "guided / paused", not
# "crashed". Still dark enough to push focus onto the card.
OVERLAY_DIM_COLOR = (0.0, 0.0, 0.0, 0.62)

# Dismiss hint shown under the card on the dim film. Tells the user
# the tour is escapable so the dimmed screen never feels like a trap.
OVERLAY_HINT_TEXT = "Press Esc or click outside the card to skip"
OVERLAY_HINT_FONT = 16
OVERLAY_HINT_COLOR = (0.78, 0.80, 0.83, 0.85)
OVERLAY_HINT_BOTTOM_GAP = 40  # px from the bottom of the host region

# ---------------------------------------------------------------------------
# Welcome dialog copy.
# ---------------------------------------------------------------------------
# Welcome card — frames the tour as a short informational walkthrough.
# The card is no longer a "pick your path" decision screen; it's the
# entry frame for a 5-step feature tour, so the copy sets that
# expectation rather than asking the user to choose anything.
WELCOME_TITLE = "Welcome to Mixar"
WELCOME_SUBHEADING = "Your AI-native 3D editor."
WELCOME_HEADING = (
    "We'll walk you through Mixar's core features in under a minute."
)
WELCOME_FOOTER = "Reopen anytime via Help → Welcome."
WELCOME_CONFIRM_LABEL = "Start the tour"

# ---------------------------------------------------------------------------
# Tour dialog layout + button labels.
# ---------------------------------------------------------------------------
TOUR_DIALOG_WIDTH = 460
TOUR_DIALOG_PROGRESS_FORMAT = "STEP {current} OF {total}"
TOUR_DIALOG_CONFIRM_NEXT = "Next step"
TOUR_DIALOG_CONFIRM_DONE = "Finish tour"

# ---------------------------------------------------------------------------
# Step copy.
# ---------------------------------------------------------------------------

# Step 1 — Moodboard.
INFO_MOODBOARD_LABEL = "Your moodboard"
INFO_MOODBOARD_BODY_1 = (
    "The moodboard is your visual canvas — drop reference images here"
)
INFO_MOODBOARD_BODY_2 = (
    "or generate them with AI. Everything else flows from these references."
)

# Step 2 — Image generation.
INFO_IMAGEGEN_LABEL = "Generate reference images"
INFO_IMAGEGEN_BODY_1 = (
    "Type what you want, pick a model, and Mixar generates"
)
INFO_IMAGEGEN_BODY_2 = (
    "the reference image straight onto your moodboard."
)

# Step 3 — Image to 3D.
INFO_IMAGE_TO_3D_LABEL = "Turn images into 3D models"
INFO_IMAGE_TO_3D_BODY_1 = (
    "Pick any image in your moodboard and hit Generate."
)
INFO_IMAGE_TO_3D_BODY_2 = (
    "Mixar reconstructs it as a 3D mesh in your scene."
)

# Step 4 — Retopology.
INFO_RETOPOLOGY_LABEL = "Clean retopology"
INFO_RETOPOLOGY_BODY_1 = (
    "AI-generated meshes are dense — the retopology tool"
)
INFO_RETOPOLOGY_BODY_2 = (
    "remeshes them into clean, quad-friendly geometry in one click."
)

# Step 5 — Mixie Chat.
INFO_MIXIE_CHAT_LABEL = "Mixie Chat — your AI partner"
INFO_MIXIE_CHAT_BODY_1 = "Mixie Chat works in two modes:"
INFO_MIXIE_CHAT_BODY_2 = (
    "• Agent — answers questions, runs tools, and edits your scene for you"
)
INFO_MIXIE_CHAT_BODY_3 = (
    "• Generate — create images, textures, and 3D models from prompts"
)

# Step 6 — Engine Mode (informational pointer to the workflow toggle).
# Purely an "FYI, this is where the full toolkit lives" card — clicking
# the highlighted menu item is not required to advance the tour. The
# user reads the copy and hits Next.
INFO_ENGINE_MODE_LABEL = "Engine Mode — the full toolkit"
# Body lines are wrapped greedily at the card's inner width. Keep
# each line short enough to fit on one visual line at the engine-
# mode step's CARD_SCALE_DEFAULT so the renderer doesn't break
# mid-sentence.
INFO_ENGINE_MODE_BODY_1 = (
    "Engine Mode lives in the top bar."
)
INFO_ENGINE_MODE_BODY_2 = (
    "Click it for Blender's full modeling,"
)
INFO_ENGINE_MODE_BODY_3 = (
    "rigging, sculpting, and rendering tools."
)

# ---------------------------------------------------------------------------
# Step 7 — bring your existing Blender add-ons across.
#
# The body line naming the plugin count is built at card-config time
# (the count isn't known until we scan), so only the fallback copy for
# "we couldn't find anything yet" lives here as a constant.
# ---------------------------------------------------------------------------
PLUGIN_IMPORT_LABEL = "Bring your add-ons along"
PLUGIN_IMPORT_BODY_FOUND = "We found {count} in your Blender {version} install."
PLUGIN_IMPORT_BODY_HINT = "We'll copy them in and switch them on for you."
PLUGIN_IMPORT_BODY_UNKNOWN_1 = (
    "Already use Blender? We can copy your add-ons and"
)
PLUGIN_IMPORT_BODY_UNKNOWN_2 = (
    "extensions into Mixar so you keep working the same way."
)
PLUGIN_IMPORT_CONFIRM_LABEL = "Import them"
PLUGIN_IMPORT_DECLINE_LABEL = "Not now"

# Outcome card — nothing found to import.
PLUGIN_IMPORT_NONE_TITLE = "No Blender install found"
PLUGIN_IMPORT_NONE_BODY_1 = (
    "We couldn't find a Blender installation with add-ons to import."
)
PLUGIN_IMPORT_NONE_BODY_2 = (
    "You can run this again any time from Preferences > Add-ons."
)

# Outcome card — import finished. Counts are filled in at card-config
# time from the import summary.
PLUGIN_IMPORT_DONE_TITLE = "Add-ons imported"
PLUGIN_IMPORT_DONE_BODY_OK = "Imported {imported} · enabled {enabled}."
PLUGIN_IMPORT_DONE_BODY_NOTHING = "Everything was already in Mixar."
PLUGIN_IMPORT_DONE_BODY_PROBLEM = "{failed} couldn't be enabled here."
PLUGIN_IMPORT_DONE_BODY_MANAGE = "Manage them in Preferences > Add-ons."
PLUGIN_IMPORT_OUTCOME_CONFIRM_LABEL = "Continue"

# ---------------------------------------------------------------------------
# Completion dialog copy.
# ---------------------------------------------------------------------------
COMPLETION_TITLE = "You're all set."
COMPLETION_SUBTITLE = "Have fun creating with Mixar."
COMPLETION_CONFIRM_LABEL = "Done"
COMPLETION_DIALOG_WIDTH = 420


# ---------------------------------------------------------------------------
# Custom GPU-rendered onboarding card (replaces invoke_props_dialog).
#
# Why custom: Blender's invoke_props_dialog anchors popups via cursor
# warping with hard-to-predict OK-button offsets (see
# ``ui_block_bounds_calc_popup``), which makes precise centring and
# proximity-positioning unreliable across DPI scales. We render the
# card ourselves with a POST_PIXEL draw handler and run the modal
# operator alongside it so we get pixel-exact positioning, hover
# feedback, and per-step layout (centre / sidebar-adjacent / above
# chat input strip).
# ---------------------------------------------------------------------------

# Geometry — all values are in unscaled UI pixels at scale=1.0.
# The layout is modelled on Apple's Freeform welcome card: a centred
# colour-tinted icon slot at the top, a big bold centred title, a
# multi-line centred body, step dots near the bottom, and a single
# bold "Continue" button in the bottom-right corner.
CARD_WIDTH = 720
CARD_MIN_HEIGHT = 640
CARD_PADDING_X = 60
CARD_PADDING_Y = 56
CARD_CORNER_RADIUS = 22
CARD_BORDER_WIDTH = 1

# Icon slot — the dark glass square at the top of every card.
CARD_ICON_SIZE = 104
CARD_ICON_RADIUS = 24
CARD_ICON_TOP_GAP = 16
CARD_ICON_BOTTOM_GAP = 42

# Vertical spacing between the card's stacked sections.
CARD_TITLE_BODY_GAP = 28
CARD_BODY_LINE_SPACING = 1.6
CARD_BODY_DOTS_GAP = 44
CARD_DOTS_BUTTONS_GAP = 36

# Step dots — Apple-style indicator. Active step is a pill (wider
# than tall), inactive steps are circles. Sizes here are circles;
# the pill width is computed as a multiple of the circle diameter.
CARD_DOT_RADIUS = 7
CARD_DOT_GAP = 30  # centre-to-centre, sized so the active pill clears neighbours
CARD_DOT_ACTIVE_PILL_WIDTH_RATIO = 2.5

# Primary "Continue" button.
CARD_BTN_HEIGHT = 60
CARD_BTN_RADIUS = 14
CARD_BTN_PADDING_X = 42

# Skip-tour link gap from the primary button (horizontal).
CARD_SKIP_GAP = 28

# Secondary ("Not now") button — a muted pill left of the primary one,
# for cards that ask a question with two real answers. Deliberately
# lower-contrast than the green primary so the recommended action still
# reads first.
CARD_ALT_GAP = 16
CARD_BTN_ALT_BG = (1.0, 1.0, 1.0, 0.10)
CARD_BTN_ALT_BG_HOVER = (1.0, 1.0, 1.0, 0.18)
CARD_BTN_ALT_TEXT = (0.86, 0.88, 0.90, 1.0)

# Back link — sits in the bottom button row to the right of Skip
# (or at the left edge when Skip is hidden). Rendered like the Skip
# link so it doesn't compete with the green Continue button. The
# label carries a leading chevron to read as "go back".
CARD_BACK_LABEL = "‹ Back"
# Horizontal gap between the Skip link and the Back link.
CARD_BACK_GAP = 24

# Font sizes (BLF points). Title is rendered with a 1-px double-draw
# offset (renderer-side) for a subtle bold look without needing a
# separate weight file.
CARD_FONT_PROGRESS = 18
CARD_FONT_TITLE = 44
CARD_FONT_BODY = 24
CARD_FONT_BUTTON = 22

# Title-shadow offset (px) and color.
CARD_TITLE_SHADOW_OFFSET = (0, -2)
CARD_TITLE_SHADOW_COLOR = (0.0, 0.0, 0.0, 0.45)

# Per-step card scale presets.
# Welcome is the entry frame for the whole tour and benefits from
# being a bit bigger / more imposing. The chat step's card sits
# above the chat input strip and uses a slightly compact scale so
# the big input footer still has room.
CARD_SCALE_DEFAULT = 1.0
CARD_SCALE_WELCOME = 1.2
CARD_SCALE_CHAT = 0.92

# Colors (RGBA, 0-1) — Mixar dark theme with green accent. The card
# is a slightly raised dark slab over the dim film, with vibrant
# green for the primary action so the next-step affordance always
# reads loud.
CARD_BG_COLOR = (0.078, 0.082, 0.094, 0.985)
CARD_BORDER_COLOR = (0.16, 0.18, 0.20, 1.0)

CARD_PROGRESS_COLOR = (0.50, 0.52, 0.56, 1.0)
CARD_TITLE_COLOR = (0.97, 0.98, 0.97, 1.0)
CARD_BODY_COLOR = (0.74, 0.76, 0.78, 1.0)

# Step dots — active is Mixar green; inactive is a muted gray that
# disappears into the card without vanishing.
CARD_DOT_ACTIVE = (0.290, 0.870, 0.502, 1.0)     # #4ADE80 ish
CARD_DOT_INACTIVE = (0.30, 0.32, 0.36, 1.0)

# Icon slot — slightly raised dark glass square so the green glyph
# inside has contrast without the slot becoming visually loud.
CARD_ICON_SLOT_BG = (0.115, 0.130, 0.150, 1.0)
CARD_ICON_GLYPH = (0.290, 0.870, 0.502, 1.0)     # Mixar green
CARD_ICON_GLYPH_DIM = (0.290, 0.870, 0.502, 0.45)

# Primary "Continue" button — Mixar green gradient.
# We render the button using the SMOOTH_COLOR shader (renderer.py)
# so the top fades from a brighter green into the base green at the
# bottom, giving it a subtle "lit" feel.
CARD_BTN_PRIMARY_BG = (0.205, 0.780, 0.430, 1.0)
CARD_BTN_PRIMARY_BG_TOP = (0.385, 0.910, 0.585, 1.0)
CARD_BTN_PRIMARY_BG_HOVER = (0.260, 0.870, 0.500, 1.0)
CARD_BTN_PRIMARY_BG_HOVER_TOP = (0.450, 0.965, 0.640, 1.0)
CARD_BTN_PRIMARY_TEXT = (0.05, 0.075, 0.060, 1.0)  # near-black on green

# Skip link — discreet, doesn't fight the green button.
CARD_BTN_SKIP_TEXT = (0.50, 0.52, 0.56, 1.0)
CARD_BTN_SKIP_TEXT_HOVER = (0.84, 0.86, 0.88, 1.0)

# Position kinds — how the card is anchored within its host area.
# WINDOW_CENTER computes the card's position so it lands at the
# geometric centre of the *whole Mixar window*, not just the host
# area. The card still draws inside the host region but its
# region-local x/y are derived from window-space coords.
CARD_POS_AREA_CENTER = "AREA_CENTER"
CARD_POS_WINDOW_CENTER = "WINDOW_CENTER"
CARD_POS_SIDEBAR_ADJACENT = "SIDEBAR_ADJACENT"
CARD_POS_ABOVE_INPUT = "ABOVE_INPUT"
# Corner-anchored positions inside the host region. TOP_LEFT is used
# for MIXIE (moodboard) hosts; TOP_RIGHT for VIEW_3D hosts so the
# card never collides with the moodboard sidebar / floating bubble.
CARD_POS_TOP_LEFT = "TOP_LEFT"
CARD_POS_TOP_RIGHT = "TOP_RIGHT"
# NEAR_BUBBLE places the card inside the host MIXIE region as close
# as possible to the floating Agent Bubble's centre — computed by
# the modal op from window/region screen coords (see
# ``_bubble_anchor_in_region`` in ``card_modal_op.py``). Falls back
# to AREA_CENTER when the bubble window isn't open.
CARD_POS_NEAR_BUBBLE = "NEAR_BUBBLE"

# Minimum gap (unscaled UI px) the card keeps from the Agent Bubble
# window when NEAR_BUBBLE positioning kicks in. Sits inside the
# host MIXIE region so the card never collides with the bubble.
CARD_BUBBLE_GAP = 40

# Sidebar width estimate (used for SIDEBAR_ADJACENT placement). The
# moodboard sidebar itself is ~280 px, but tool dropdowns / picker
# popovers inside it open leftward and can extend ~200 px past the
# sidebar edge. We pad the reserved width so those popovers don't
# land on top of the card.
CARD_SIDEBAR_WIDTH = 480
CARD_AREA_MARGIN = 40

# Chat input strip estimate (used for ABOVE_INPUT placement) — the
# distance from the chat area's bottom edge to where the card's
# bottom should sit. The Mixie Chat footer is 3 input rows (~20 px
# each, scaled) plus mode dropdown + send button + padding. We use a
# tighter gutter now so the bigger chat card fits comfortably.
CARD_CHAT_INPUT_GUTTER = 150

# The single op_idname used for every step's card now — no more
# per-step dialog operators.
OP_CARD_MODAL = "mixar.onboarding_card"

# Per-step icon identifiers — the renderer dispatches to a small
# pure-GPU glyph drawer for each one. Keeping these as simple string
# constants (rather than enums) so step config dicts stay readable.
ICON_WELCOME = "WELCOME"
ICON_MOODBOARD = "MOODBOARD"
ICON_IMAGEGEN = "IMAGEGEN"
ICON_IMAGE_TO_3D = "IMAGE_TO_3D"
ICON_RETOPOLOGY = "RETOPOLOGY"
ICON_CHAT = "CHAT"
ICON_CHECKMARK = "CHECKMARK"
ICON_ENGINE = "ENGINE"


# ---------------------------------------------------------------------------
# Per-step highlight border — a green gradient stroke painted around
# the UI element each step is describing. Drawn on top of the dim
# film by ``core/overlay/highlight.py``.
# ---------------------------------------------------------------------------

# Gradient colour stops (RGBA). Top = brighter, bottom = base green
# — matches the Continue button so the highlight reads as the same
# accent across the tour.
HIGHLIGHT_TOP_COLOR = (0.450, 0.980, 0.640, 1.0)
HIGHLIGHT_BOTTOM_COLOR = (0.205, 0.780, 0.430, 1.0)

# Stroke thickness in unscaled UI px (multiplied by ui_scale at draw).
HIGHLIGHT_THICKNESS = 4

# Corner radius for the highlight border in unscaled UI px.
HIGHLIGHT_CORNER_RADIUS = 10

# Padding (unscaled UI px) added around sub-region targets like the
# chat mode dropdown — keeps the border from kissing the widget edge.
HIGHLIGHT_TARGET_PAD = 4

# Inset from the moodboard area's WINDOW region when highlighting it.
# Smaller than padded highlights because we want the border crisp
# against the canvas edges.
HIGHLIGHT_REGION_INSET = 3

# Inset from the topbar's HEADER region when highlighting the workspace
# tabs + the Zen/Engine menu items. Small — the topbar is only
# ~30 px tall, so a big inset would leave no room for the border.
HIGHLIGHT_TOPBAR_INSET = 2

# ---------------------------------------------------------------------------
# Topbar highlight target sub-regions.
#
# The topbar HEADER region spans the whole window width but only a
# small part of it is actually relevant per step. These constants are
# in unscaled UI px from the LEFT edge of the topbar HEADER region
# (scaled at draw time so the bounds track DPI / ui_scale).
#
# Values are tuned empirically — refine via screenshots if Blender's
# default font / menu padding ever changes the rendered layout.
# ---------------------------------------------------------------------------

# Engine mode menu item — sits at the END of the editor_menus
# strip (File · Edit · Render · Window · Help · Engine Mode). Values
# are pre-scale; ``_scaled()`` multiplies by ``ui_scale`` at draw
# time so retina/HiDPI lands the highlight on the same visual button.
TOPBAR_MODE_BUTTON_X = 230
TOPBAR_MODE_BUTTON_W = 100

# Chat mode dropdown — values mirror the C++ defaults in
# ``mixie_chat_footer_constants.hh`` and the layout in
# ``mixie_chat_footer_layout.cc``. All at scale=1.0; multiplied by
# ``ui_scale`` at draw time.
CHAT_DROPDOWN_X = 8       # FOOTER_DEFAULT_SIDE_PADDING
CHAT_DROPDOWN_Y = 4       # tighter than the 6px C++ default — the
                          # actual rendered widget sits slightly
                          # higher than the row's bottom padding
CHAT_DROPDOWN_W = 160     # FOOTER_DROPDOWN_WIDTH_BASE
CHAT_DROPDOWN_H = 38      # widget renders slightly shorter than
                          # the 44px button-row height it sits in

# Sidebar panel heights for STEP_INFO_IMAGEGEN / IMAGE_TO_3D /
# RETOPOLOGY in unscaled UI px — FALLBACK ONLY. The highlight now
# measures the real rendered panel extent from the region View2D's
# ``tot_rect`` (Mixar RNA addition, see ``rna_screen.cc``), which is
# required because the catalog-driven tabs render schema-dependent
# content whose height varies per selected mode / model. These
# estimates are used only when running against a build without that
# RNA overlay.
SIDEBAR_PANEL_H_IMAGEGEN = 380     # header + prompt + reference + settings + generate
SIDEBAR_PANEL_H_IMAGE_TO_3D = 310  # header + prompt + input image + settings + generate
SIDEBAR_PANEL_H_RETOPOLOGY = 250   # header + mesh info + hint + settings + generate

# Horizontal inset inside the UI region — cuts the vertical tab
# strip out of the highlight (tabs run on the right edge ~24 px wide).
SIDEBAR_TAB_STRIP_WIDTH = 24
# Pad applied around the sidebar panel highlight so the border isn't
# flush with the panel edges.
SIDEBAR_PANEL_PAD = 4

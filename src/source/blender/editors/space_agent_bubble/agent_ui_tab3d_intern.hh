/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Shared internals of the island's 3D tab (agent_ui_tab3d.cc +
 * agent_ui_tab3d_params.cc). Tokens are ISLAND units measured off
 * `3d.svg` (island origin at artboard 267,340 — the same frame grid as
 * agent_ui_theme.hh; this header only ADDS tokens, the shared ones stay
 * in the theme header).
 */

#pragma once

#include "BLI_rect.h"
#include "RNA_types.hh"

struct ARegion;
struct bContext;
struct uiBlock;

/* -------------------------------------------------------------------- */
/** \name Design tokens (island units) — 3d.svg
 * \{ */

/* Params strip: rows of chips on the panel, first row top at island y=226,
 * second at 288 (pitch 62). Chips share the Agent chip metrics (h 44, rx 14,
 * font 18) — reuse AGENT_CHIP_* for those. */
#define T3D_ROW_X 37
#define T3D_ROW0_Y 226
#define T3D_ROW_PITCH 62
#define T3D_CHIP_GAP 21
#define T3D_CHIP_PAD_X 24

/* Prompt box: 6,363 1298x200 rx28 #121212; its bottom follows the panel's
 * (the card stretches), keeping a 4-unit inset. Ghost text ink at (44,414)
 * -> 38 units below the box top, font 24 (= AGENT_PROMPT_FONT). */
#define T3D_BOX_X 6
#define T3D_BOX_Y 363
#define T3D_BOX_W 1298
#define T3D_BOX_RADIUS 28
#define T3D_BOX_BOTTOM_INSET 4
#define T3D_PROMPT_X 44

/* Bottom row INSIDE the box: Upload chip at box-left 31, Generate at
 * box-right inset 4; both 16 units above the box bottom, h 44. */
#define T3D_CHIP_BOTTOM_INSET 16
#define T3D_UPLOAD_X 37
#define T3D_GENERATE_W 114

/* Palette (3d.svg fills; alpha ALWAYS stated). */
#define T3D_COL_PANEL_TOP {0.176f, 0.176f, 0.176f, 1.0f}    /* #2D2D2D */
#define T3D_COL_PANEL_BOTTOM {0.075f, 0.078f, 0.075f, 1.0f} /* #131413 */
#define T3D_COL_CHIP {0.192f, 0.192f, 0.192f, 1.0f}         /* #313131 */
#define T3D_COL_CHIP_THUMB {0.282f, 0.282f, 0.282f, 1.0f}   /* #484848 */
#define T3D_COL_SLIDER {0.345f, 0.341f, 0.341f, 1.0f}       /* #585757 handle */
#define T3D_COL_SLIDER_FILL {0.443f, 0.443f, 0.443f, 1.0f}  /* mid of #474747..#ADADAD */
#define T3D_COL_BOX {0.071f, 0.071f, 0.071f, 1.0f}          /* #121212 */
#define T3D_COL_UPLOAD {0.114f, 0.114f, 0.114f, 1.0f}       /* #1D1D1D */
#define T3D_COL_GENERATE {0.102f, 0.251f, 0.149f, 1.0f}     /* #1A4026 */

/** \} */

/* -------------------------------------------------------------------- */
/** \name Shared painter helpers (agent_ui_tab3d.cc)
 * \{ */

void t3d_fill_round(const rctf *rect, float radius, const float col[4]);
float t3d_text_width(const char *text, float size);
void t3d_label_left(const char *text, float x, float cy, float size, const float col[4]);
void t3d_label_centre(const char *text, float cx, float cy, float size, const float col[4]);
void t3d_fit_text(char *text, float max_w, float size);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Params strip (agent_ui_tab3d_params.cc)
 * \{ */

/**
 * Paint + bind the schema params of the ACTIVE (service, model) as island
 * chips, flowing left-to-right from (\a x0, \a y0_top) in region pixels,
 * wrapping by the row pitch, never below \a y_floor. Enum params with <= 4
 * items render as a segmented control (each segment a `wm.context_set_enum`),
 * larger enums as a dropdown chip opening `wm.context_menu_enum`; booleans as
 * an ON/OFF chip on `wm.context_toggle`; ints/floats as a chip hosting a real
 * embossed NumSlider bound straight to the group property.
 *
 * \param group_ptr: the WindowManager param-group instance (engine-registered).
 * \param group_path: bpy.context-relative path to it, for the context ops.
 * \param chips_block: unembossed block for the painted controls.
 * \param slider_block: embossed block for NumSlider widgets.
 */
void agent_ui_tab3d_params_draw(const bContext *C,
                                PointerRNA *group_ptr,
                                const char *group_path,
                                uiBlock *chips_block,
                                uiBlock *slider_block,
                                float x0,
                                float y0_top,
                                float x_max,
                                float y_floor,
                                float u);

/** \} */

/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Shared internals of the Gaussian Splat tab, split across
 * agent_ui_tabsplat.cc (state + controls) and agent_ui_tabsplat_paint.cc
 * (geometry + painting) under the 500-line rule.
 */

#pragma once

#include "BLI_rect.h"
#include "RNA_access.hh"

struct bContext;

/* Artboard-unit metrics measured from the "gaussian splats" frame (island
 * origin 267,340; deltas relative to the card panel's top-left at island
 * (2,201)). */
#define SPLAT_FONT 18
#define SPLAT_ROW_H 44
#define SPLAT_ROW_RADIUS 14
#define SPLAT_PARAMS_Y 31
#define SPLAT_MODE_X 21
#define SPLAT_MODE_W 155
#define SPLAT_MODE_SPLIT 78 /* Text half width (99 - 21). */
#define SPLAT_SEG_INSET 3
#define SPLAT_MODEL_X 197
#define SPLAT_MODEL_W 137
#define SPLAT_LOD_X 353
#define SPLAT_LOD_W 230
#define SPLAT_BOX_INSET_X 4
#define SPLAT_BOX_Y 105
#define SPLAT_CHIP_ROW_DY 302 /* Chip row top, from panel top. */
#define SPLAT_CHIP_UPLOAD_X 21
#define SPLAT_CHIP_UPLOAD_W 150
#define SPLAT_CHIP_CAPTURE_X 183
#define SPLAT_CHIP_CAPTURE_W 183
#define SPLAT_MOOD_LABEL_X 390
#define SPLAT_SWITCH_X 646
#define SPLAT_SWITCH_W 46
#define SPLAT_SWITCH_H 26
#define SPLAT_THUMB_X 723
#define SPLAT_THUMB_EDGE 45
#define SPLAT_THUMB_GAP 7
#define SPLAT_GEN_X 1172
#define SPLAT_GEN_W 114
#define SPLAT_PROMPT_PAD_X 39 /* Ghost text inset from panel left (43 - 4). */

#define SPLAT_ENUM_MAX 6

struct SplatEnumItem {
  char ident[64];
  char label[64];
  bool active;
};

/** Resolved live state; valid only when splat_state_resolve returned true. */
struct SplatTabState {
  PointerRNA tab;    /* scene.mixie_moodboard_sidebar.tab_world_labs */
  PointerRNA params; /* wm.mixar_genparams_world_labs__<slug> */
  PropertyRNA *mode_prop;
  PropertyRNA *lod_prop;
  char model_slug[128];
  char model_label[128];
  char group_attr[192];
  char mode_ident[32];
  bool image_mode;
  bool use_selected;
};

/** Region-space rects for every element, built from the panel rect. */
struct SplatPaneRects {
  rctf mode_track, mode_text, mode_image;
  rctf model_chip;
  rctf lod_track;
  rctf lod_seg[SPLAT_ENUM_MAX];
  int lod_count;
  rctf prompt_box;
  rctf prompt_field;
  rctf chip_upload, chip_capture;
  rctf moodboard_switch;
  rctf thumbs; /* Left edge of the thumbnail run. */
  rctf btn_generate;
};

bool splat_state_resolve(const bContext *C, SplatTabState *r_state);
int splat_enum_items_get(const bContext *C,
                         PointerRNA *ptr,
                         PropertyRNA *prop,
                         SplatEnumItem *r_items,
                         int max_items);

void splat_pane_rects_build(const rctf &panel, float u, const SplatEnumItem *lod_items, int lod_count, SplatPaneRects *r_rects);
void splat_pane_paint(const bContext *C,
                      const SplatTabState &state,
                      const SplatPaneRects &rects,
                      const SplatEnumItem *mode_items,
                      int mode_count,
                      const SplatEnumItem *lod_items,
                      int lod_count,
                      float u);
void splat_label_centre(
    const char *text, float cx, float cy, float size, const float col[4]);

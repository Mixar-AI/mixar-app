/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Shared internals of the past-chats overlay, split across:
 *   - mixie_chat_history_overlay.cc  (panel layout + drawing)
 *   - mixie_chat_history_events.cc   (clicks, keys, scroll, cursor)
 *   - mixie_chat_history_util.cc     (RNA readers, text/glyph helpers)
 */

#pragma once

#include <cstddef>

#include "BLI_vector.hh"

struct ARegion;
struct bContext;
struct MixieChatRuntime;
struct wmWindowManager;

/* -------------------------------------------------------------------- */
/** \name Geometry Constants (base px, scaled by UI_SCALE_FAC at draw time)
 * \{ */

inline constexpr float HIST_PANEL_MAX_WIDTH = 480.0f;
inline constexpr float HIST_PANEL_SIDE_MARGIN = 12.0f;
inline constexpr float HIST_PANEL_TOP_MARGIN = 10.0f;
inline constexpr float HIST_PANEL_RADIUS = 14.0f;
inline constexpr float HIST_PANEL_PAD = 12.0f;
inline constexpr float HIST_HEADER_HEIGHT = 46.0f;
inline constexpr float HIST_SEARCH_AREA_HEIGHT = 42.0f;
inline constexpr float HIST_SEARCH_FIELD_HEIGHT = 30.0f;
inline constexpr float HIST_GROUP_HEADER_HEIGHT = 26.0f;
inline constexpr float HIST_ROW_HEIGHT = 40.0f;
inline constexpr float HIST_ROW_RADIUS = 9.0f;
inline constexpr float HIST_ROW_SIDE_INSET = 6.0f;
inline constexpr float HIST_DOT_RADIUS = 3.5f;
inline constexpr float HIST_TITLE_INDENT = 26.0f;
inline constexpr float HIST_DELETE_SIZE = 22.0f;
inline constexpr float HIST_DELETE_RIGHT_INSET = 8.0f;
inline constexpr float HIST_CLOSE_SIZE = 24.0f;
inline constexpr float HIST_LIST_MAX_HEIGHT = 12.0f * HIST_ROW_HEIGHT;
inline constexpr float HIST_OPEN_ANIM_DURATION = 0.18f; /* seconds */
inline constexpr float HIST_OPEN_SLIDE_PX = 8.0f;

/* Smooth scrolling: wheel step in px and the exponential approach rate
 * (per second) the draw uses to ease history_scroll_px toward
 * history_scroll_target. */
inline constexpr float HIST_WHEEL_STEP_PX = 52.0f;
inline constexpr float HIST_SCROLL_APPROACH_RATE = 16.0f;

/** \} */

/* -------------------------------------------------------------------- */
/** \name Colors (Mixar dark surface language; alpha scaled by open anim)
 * \{ */

inline constexpr float HIST_COL_SCRIM[4] = {0.02f, 0.03f, 0.04f, 0.42f};
inline constexpr float HIST_COL_PANEL[4] = {0.105f, 0.115f, 0.135f, 0.995f};
inline constexpr float HIST_COL_PANEL_OUTLINE[4] = {1.0f, 1.0f, 1.0f, 0.075f};
inline constexpr float HIST_COL_PANEL_SHADOW[4] = {0.0f, 0.0f, 0.0f, 0.35f};
inline constexpr float HIST_COL_HEADER_TEXT[4] = {0.92f, 0.94f, 0.97f, 1.0f};
inline constexpr float HIST_COL_MUTED[4] = {0.52f, 0.56f, 0.61f, 1.0f};
inline constexpr float HIST_COL_DIVIDER[4] = {1.0f, 1.0f, 1.0f, 0.06f};
/* Row hover comes from the theme: theme.space_mixie_chat.chat_history_row_hover
 * (chat_ui_get_history_row_hover_color), seeded by the Python bootstrap. */
inline constexpr float HIST_COL_TITLE[4] = {0.86f, 0.88f, 0.91f, 0.96f};
inline constexpr float HIST_COL_TITLE_CURRENT[4] = {0.97f, 0.98f, 1.0f, 1.0f};
inline constexpr float HIST_COL_DELETE[4] = {0.55f, 0.58f, 0.62f, 0.75f};
inline constexpr float HIST_COL_DELETE_HOVER[4] = {0.95f, 0.42f, 0.42f, 1.0f};
inline constexpr float HIST_COL_DELETE_HOVER_BG[4] = {1.0f, 1.0f, 1.0f, 0.09f};
inline constexpr float HIST_COL_DELETE_ARMED_BG[4] = {0.95f, 0.42f, 0.42f, 0.18f};
inline constexpr float HIST_COL_SCROLL_THUMB[4] = {1.0f, 1.0f, 1.0f, 0.16f};
inline constexpr float HIST_COL_SEARCH_BG[4] = {1.0f, 1.0f, 1.0f, 0.045f};
inline constexpr float HIST_COL_SEARCH_OUTLINE[4] = {1.0f, 1.0f, 1.0f, 0.08f};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Shared Types + Helpers
 * \{ */

/** Local snapshot of one history entry read from RNA. */
struct HistoryDrawEntry {
  char title[200];
  char when[24];
  char group[32];
  char session_id[128];
};

/* mixie_chat_history_util.cc */

bool mixie_chat_history_read_visible(wmWindowManager *wm);
void mixie_chat_history_read_entries(wmWindowManager *wm,
                                     blender::Vector<HistoryDrawEntry> &r_items);
void mixie_chat_history_reset_runtime(MixieChatRuntime *rt);

/** Dispatch a Python operator that takes a single session_id string. */
void mixie_chat_history_dispatch_session_op(bContext *C,
                                            ARegion *region,
                                            const char *op_idname,
                                            const char *session_id);

void hist_draw_label(
    const char *text, int font_id, int font_px, float x, float baseline_y, const float color[4]);
float hist_text_width(const char *text, int font_id, int font_px);
void hist_text_ellipsis(
    const char *src, int font_id, int font_px, float max_width, char *dst, size_t dst_size);
/** Two crossing GPU lines forming an X glyph (delete / close buttons). */
void hist_draw_x_glyph(float cx, float cy, float half, const float color[4], float scale);

/** \} */

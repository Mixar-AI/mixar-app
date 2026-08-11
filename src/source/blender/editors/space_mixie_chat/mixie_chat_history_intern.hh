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

#include "mixie_chat_ui_tokens.hh"

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

/* These are the same design tokens the transcript uses (mixie_chat_ui_tokens.hh)
 * so an overlay opened over the chat reads as the same surface lifted, not as a
 * separate panel that happens to be dark. Shared by BOTH the past-chats and the
 * Project Rules overlays — an edit here moves both.
 *
 * The white-alpha values that remain (divider, scroll thumb, armed-delete wash)
 * are deliberate: they are washes over an already-composited panel, so they must
 * track whatever is beneath them rather than pin to an opaque value. */
inline constexpr float HIST_COL_SCRIM[4] = {CHAT_TOK_PAGE, 0.42f};
inline constexpr float HIST_COL_PANEL[4] = {CHAT_TOK_SURFACE, 0.995f};
inline constexpr float HIST_COL_PANEL_OUTLINE[4] = {CHAT_TOK_LINE_2, 1.0f};
inline constexpr float HIST_COL_PANEL_SHADOW[4] = {0.0f, 0.0f, 0.0f, 0.35f};
inline constexpr float HIST_COL_HEADER_TEXT[4] = {CHAT_TOK_INK, 1.0f};
inline constexpr float HIST_COL_MUTED[4] = {CHAT_TOK_INK_3, 1.0f};
inline constexpr float HIST_COL_DIVIDER[4] = {1.0f, 1.0f, 1.0f, 0.06f};
/* Row hover comes from the theme: theme.space_mixie_chat.chat_history_row_hover
 * (chat_ui_get_history_row_hover_color), seeded by the Python bootstrap. */
/* Row titles are the PRIMARY content of the picker — the text you read to
 * choose — so they take full ink, not the meta tier. The current chat is
 * distinguished by its row background, not by dimming every other row. */
inline constexpr float HIST_COL_TITLE[4] = {CHAT_TOK_INK, 1.0f};
inline constexpr float HIST_COL_TITLE_CURRENT[4] = {CHAT_TOK_INK, 1.0f};
inline constexpr float HIST_COL_DELETE[4] = {CHAT_TOK_INK_3, 1.0f};
inline constexpr float HIST_COL_DELETE_HOVER[4] = {CHAT_TOK_RED, 1.0f};
inline constexpr float HIST_COL_DELETE_HOVER_BG[4] = {1.0f, 1.0f, 1.0f, 0.09f};
inline constexpr float HIST_COL_DELETE_ARMED_BG[4] = {CHAT_TOK_RED, 0.18f};
inline constexpr float HIST_COL_SCROLL_THUMB[4] = {1.0f, 1.0f, 1.0f, 0.16f};
inline constexpr float HIST_COL_SEARCH_BG[4] = {CHAT_TOK_FIELD, 1.0f};
inline constexpr float HIST_COL_SEARCH_OUTLINE[4] = {CHAT_TOK_LINE, 1.0f};

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

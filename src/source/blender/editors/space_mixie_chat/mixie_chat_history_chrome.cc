/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * The past-chats / Checkpoints card's chrome: scrim, shadow, card body,
 * header (title, count, close X, divider), the checkpoints footer, and the
 * empty states. The overlay (mixie_chat_history_overlay.cc) measures the
 * layout into a HistoryDrawFrame and calls in here; rows are drawn by
 * mixie_chat_history_rows.cc.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLI_math_vector.h"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_string_utf8.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BLF_api.hh"

#include "GPU_state.hh"

#include "UI_interface.hh"

#include "mixie_chat_history_intern.hh"
#include "mixie_chat_intern.hh"

namespace blender {

void mixie_chat_history_draw_chrome(const HistoryDrawFrame &f)
{
  MixieChatRuntime *rt = f.rt;
  const bool checkpoints = f.checkpoints;
  const bool locked = f.locked;
  const bool store_empty = f.store_empty;
  const bool no_matches = f.no_matches;
  const char *notice = f.notice;
  const int font_id = f.font_id;
  const int title_px = f.title_px;
  const int meta_px = f.meta_px;
  const int group_px = f.group_px;
  const int header_px = f.header_px;
  const float scale = f.scale;
  const float pad = f.pad;
  const float header_h = f.header_h;
  const float slide = f.slide;
  const float ease = f.ease;
  const float panel_x = f.panel_x;
  const float panel_w = f.panel_w;
  const float list_top = f.list_top;
  const float list_bottom = f.list_bottom;
  const float mouse_x = f.mouse_x;
  const float mouse_y = f.mouse_y;
  const rctf &panel = f.panel;
  const int winx = f.winx;
  const int winy = f.winy;
  UNUSED_VARS(rt, checkpoints, locked, store_empty, no_matches, notice, font_id, title_px);
  UNUSED_VARS(meta_px, group_px, header_px, scale, pad, header_h, slide, ease);
  UNUSED_VARS(panel_x, panel_w, list_top, list_bottom, mouse_x, mouse_y, panel, winx, winy);
  const float radius = HIST_PANEL_RADIUS * scale;

  /* Scrim: dim the chat behind the card. */
  {
    rctf full;
    BLI_rctf_init(&full, 0.0f, float(winx), 0.0f, float(winy));
    float scrim[4] = {HIST_COL_SCRIM[0], HIST_COL_SCRIM[1], HIST_COL_SCRIM[2],
                      HIST_COL_SCRIM[3] * ease};
    chat_ui_draw_rounded_rect(&full, 0.0f, scrim);
  }

  /* Soft shadow substitute: a slightly larger dark card behind. */
  {
    rctf shadow = panel;
    const float grow = 3.0f * scale;
    shadow.xmin -= grow;
    shadow.xmax += grow;
    shadow.ymin -= grow * 1.6f;
    shadow.ymax += grow * 0.4f;
    float col[4] = {HIST_COL_PANEL_SHADOW[0], HIST_COL_PANEL_SHADOW[1], HIST_COL_PANEL_SHADOW[2],
                    HIST_COL_PANEL_SHADOW[3] * ease};
    chat_ui_draw_rounded_rect(&shadow, radius + grow, col);
  }

  /* Card. */
  {
    float fill[4] = {HIST_COL_PANEL[0], HIST_COL_PANEL[1], HIST_COL_PANEL[2],
                     HIST_COL_PANEL[3] * ease};
    float outline[4] = {HIST_COL_PANEL_OUTLINE[0], HIST_COL_PANEL_OUTLINE[1],
                        HIST_COL_PANEL_OUTLINE[2], HIST_COL_PANEL_OUTLINE[3] * ease};
    chat_ui_draw_rounded_rect(&panel, radius, fill);
    chat_ui_draw_rounded_rect_outline(&panel, radius, outline, 1.0f);
  }

  /* Header: "Chats" + count left, close X right, hairline divider below. */
  {
    const float header_center = panel.ymax - header_h * 0.5f;
    const float baseline = header_center - float(header_px) * 0.35f;

    float title_col[4] = {HIST_COL_HEADER_TEXT[0], HIST_COL_HEADER_TEXT[1],
                          HIST_COL_HEADER_TEXT[2], HIST_COL_HEADER_TEXT[3] * ease};
    const char *card_title = checkpoints ? "Checkpoints" : "Chats";
    hist_draw_label(card_title, font_id, header_px, panel.xmin + pad, baseline, title_col);

    if (!store_empty) {
      char count_buf[32];
      if (rt->history_search[0] != '\0') {
        SNPRINTF(count_buf, "%d / %d", f.filtered_count, f.entries_count);
      }
      else {
        SNPRINTF(count_buf, "%d", f.entries_count);
      }
      float count_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                            HIST_COL_MUTED[3] * ease};
      const float title_w = hist_text_width(card_title, font_id, header_px);
      hist_draw_label(count_buf, font_id, meta_px, panel.xmin + pad + title_w + 8.0f * scale,
                      header_center - float(meta_px) * 0.35f, count_col);
    }

    /* Close button (X, ring on hover). */
    {
      const bool close_hovered = BLI_rctf_isect_pt(&rt->history_close_bounds, mouse_x, mouse_y);
      const float close_cx = BLI_rctf_cent_x(&rt->history_close_bounds);
      const float close_cy = BLI_rctf_cent_y(&rt->history_close_bounds) - slide;
      if (close_hovered) {
        rctf ring = rt->history_close_bounds;
        ring.ymin -= slide;
        ring.ymax -= slide;
        float ring_col[4] = {HIST_COL_DELETE_HOVER_BG[0], HIST_COL_DELETE_HOVER_BG[1],
                             HIST_COL_DELETE_HOVER_BG[2], HIST_COL_DELETE_HOVER_BG[3] * ease};
        chat_ui_draw_rounded_rect(&ring, HIST_CLOSE_SIZE * 0.5f * scale, ring_col);
      }
      float x_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                        (close_hovered ? 1.0f : 0.8f) * ease};
      if (close_hovered) {
        x_col[0] = HIST_COL_HEADER_TEXT[0];
        x_col[1] = HIST_COL_HEADER_TEXT[1];
        x_col[2] = HIST_COL_HEADER_TEXT[2];
      }
      hist_draw_x_glyph(close_cx, close_cy, 4.6f * scale, x_col, scale);
    }

    rctf divider;
    BLI_rctf_init(&divider,
                  panel.xmin + pad,
                  panel.xmax - pad,
                  panel.ymax - header_h,
                  panel.ymax - header_h + 1.0f * scale);
    float div_col[4] = {HIST_COL_DIVIDER[0], HIST_COL_DIVIDER[1], HIST_COL_DIVIDER[2],
                        HIST_COL_DIVIDER[3] * ease};
    chat_ui_draw_rounded_rect(&divider, 0.0f, div_col);
  }


  /* Footer (checkpoints): muted explanation, or the amber lock reason. */
  for (int line = 0; line < f.footer_count; line++) {
    const float baseline = list_bottom - (line + 1) * f.footer_line_h - slide + 4.0f * scale;
    float col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                    HIST_COL_MUTED[3] * ease};
    if (notice[0] != '\0') {
      col[0] = 0.95f;
      col[1] = 0.78f;
      col[2] = 0.42f;
    }
    char clipped[200];
    hist_text_ellipsis(f.footer_lines[line], font_id, group_px, panel_w - 2.0f * pad,
                       clipped, sizeof(clipped));
    hist_draw_label(clipped, font_id, group_px, panel.xmin + pad, baseline, col);
  }

}

/** Draws the "nothing to list" message in the list area and ends the frame
 * (the caller returns right after). */
void mixie_chat_history_draw_empty(const HistoryDrawFrame &f)
{
  MixieChatRuntime *rt = f.rt;
  const bool checkpoints = f.checkpoints;
  const bool locked = f.locked;
  const bool store_empty = f.store_empty;
  const bool no_matches = f.no_matches;
  const char *notice = f.notice;
  const int font_id = f.font_id;
  const int title_px = f.title_px;
  const int meta_px = f.meta_px;
  const int group_px = f.group_px;
  const int header_px = f.header_px;
  const float scale = f.scale;
  const float pad = f.pad;
  const float header_h = f.header_h;
  const float slide = f.slide;
  const float ease = f.ease;
  const float panel_x = f.panel_x;
  const float panel_w = f.panel_w;
  const float list_top = f.list_top;
  const float list_bottom = f.list_bottom;
  const float mouse_x = f.mouse_x;
  const float mouse_y = f.mouse_y;
  const rctf &panel = f.panel;
  const int winx = f.winx;
  const int winy = f.winy;
  UNUSED_VARS(rt, checkpoints, locked, store_empty, no_matches, notice, font_id, title_px);
  UNUSED_VARS(meta_px, group_px, header_px, scale, pad, header_h, slide, ease);
  UNUSED_VARS(panel_x, panel_w, list_top, list_bottom, mouse_x, mouse_y, panel, winx, winy);
  /* Empty states: no archived chats at all / no titles match the query. */
  if (store_empty || no_matches) {
    float title_col[4] = {HIST_COL_TITLE[0], HIST_COL_TITLE[1], HIST_COL_TITLE[2],
                          HIST_COL_TITLE[3] * ease};
    float hint_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                         HIST_COL_MUTED[3] * ease};

    const char *empty_text = checkpoints ? "No turns yet" :
                             store_empty ? "No past chats yet" :
                                           "No chats match your search";
    const char *hint_text = checkpoints ? "A checkpoint is taken before each turn" :
                            store_empty ? "New Chat saves the current conversation here" :
                                          "Backspace to edit, Esc to clear";
    const float cx = (panel.xmin + panel.xmax) * 0.5f;
    const float cy = (list_top + list_bottom) * 0.5f - slide;

    float w = hist_text_width(empty_text, font_id, title_px);
    hist_draw_label(empty_text, font_id, title_px, cx - w * 0.5f, cy + 4.0f * scale, title_col);
    w = hist_text_width(hint_text, font_id, meta_px);
    hist_draw_label(hint_text, font_id, meta_px, cx - w * 0.5f,
                    cy - (4.0f * scale + float(meta_px)), hint_col);

    GPU_blend(GPU_BLEND_NONE);
    /* Cursor is owned by mixie_chat_history_cursor (region event_cursor
     * callback) — never set it from a draw callback: draws fire for reasons
     * unrelated to the mouse (streaming redraws, scroll settling, the anim
     * pump), and would stomp the window cursor even while the mouse is over
     * another editor. */
  }

}

}  // namespace blender

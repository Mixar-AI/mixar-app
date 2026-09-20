/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * The past-chats / Checkpoints card's rows: section headers, hover and
 * keyboard selection, the armed state (a red "Delete?" on a chat, the
 * accent prompt Python computed per checkpoint row, "Revert turns 3–5?"),
 * the current-chat dot, time label, ellipsis-clipped title, delete X, plus
 * the scrollbar thumb. Hit rects for every row are recorded on the runtime
 * for the events file. Layout comes from mixie_chat_history_overlay.cc as a
 * HistoryDrawFrame.
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

static const float COL_ACCENT[4] = CHAT_ACCENT_LIVE;

void mixie_chat_history_draw_rows(const HistoryDrawFrame &f)
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
  const blender::Vector<HistoryDrawEntry> &entries = *f.entries;
  const blender::Vector<HistoryDisplayItem> &items = *f.items;
  const char *current_id = f.current_id;
  const float view_h = f.view_h;
  const float content_h = f.content_h;
  const float max_scroll = f.max_scroll;

  /* Rows + group headers, scissor-clipped to the list viewport so the
   * pixel-smooth scroll can show partial rows at both edges. Regions draw
   * into a REGION-SIZED offscreen buffer (wm_draw_region_bind sets the
   * scissor to 0,0,winx,winy) — so GPU_scissor takes region-local coords
   * here, NOT window coords; restore the full-region scissor after. */
  const bool has_scrollbar = (content_h > view_h + 0.5f);
  const float row_xmin = panel_x + HIST_ROW_SIDE_INSET * scale;
  const float row_xmax =
      panel_x + panel_w - HIST_ROW_SIDE_INSET * scale - (has_scrollbar ? 8.0f * scale : 0.0f);

  bool any_hovered = false;

  GPU_scissor(int(std::floor(panel_x)),
              int(std::floor(list_bottom)),
              int(std::ceil(panel_w)) + 1,
              int(std::ceil(view_h)) + 1);

  for (const HistoryDisplayItem &item : items) {
    /* Content-space -> screen-space: scrolling moves content up. */
    const float item_top = list_top - item.content_top + rt->history_scroll_px;
    const float item_bottom = item_top - item.height;

    if (item.entry_index < 0) {
      /* Date-group section header. */
      if (item_bottom <= list_top + item.height && item_top >= list_bottom - item.height) {
        const float baseline = (item_top + item_bottom) * 0.5f - slide - float(group_px) * 0.30f;
        float group_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                              HIST_COL_MUTED[3] * 0.9f * ease};
        hist_draw_label(item.group, font_id, group_px, row_xmin + 8.0f * scale, baseline,
                        group_col);
      }
      continue;
    }

    const HistoryDrawEntry &entry = entries[item.entry_index];
    const bool is_current = (current_id[0] != '\0') && STREQ(entry.session_id, current_id);
    const bool is_armed = (rt->history_confirm_id[0] != '\0') &&
                          STREQ(entry.session_id, rt->history_confirm_id);

    const float row_top = item_top;
    const float row_bottom = item_bottom;
    const float row_center = (row_top + row_bottom) * 0.5f;

    /* Hit rects for EVERY filtered row (even offscreen ones — keyboard
     * selection needs their content offsets; mouse hits are additionally
     * gated on history_list_bounds). */
    HistoryRowHit hit;
    BLI_rctf_init(&hit.bounds, row_xmin, row_xmax, row_bottom, row_top);
    const float del_half = HIST_DELETE_SIZE * 0.5f * scale;
    const float del_cx = row_xmax - HIST_DELETE_RIGHT_INSET * scale - del_half;
    if (checkpoints) {
      /* No delete affordance: the whole row is the (arm-to-confirm) target. */
      BLI_rctf_init(&hit.delete_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
    }
    else {
      BLI_rctf_init(&hit.delete_bounds,
                    del_cx - del_half,
                    del_cx + del_half,
                    row_center - del_half,
                    row_center + del_half);
    }
    hit.content_top = item.content_top;
    BLI_strncpy(hit.session_id, entry.session_id, sizeof(hit.session_id));
    BLI_strncpy_utf8(hit.title, entry.title, sizeof(hit.title));
    BLI_strncpy_utf8(hit.group, entry.group, sizeof(hit.group));
    const bool in_list = BLI_rctf_isect_pt(&rt->history_list_bounds, mouse_x, mouse_y);
    hit.is_hovered = !locked && in_list && BLI_rctf_isect_pt(&hit.bounds, mouse_x, mouse_y);
    hit.delete_hovered = hit.is_hovered &&
                         BLI_rctf_isect_pt(&hit.delete_bounds, mouse_x, mouse_y);
    any_hovered |= hit.is_hovered;
    const int row_index = int(rt->history_rows.size());
    rt->history_rows.append(hit);

    /* Skip drawing rows fully outside the viewport. */
    if (row_bottom > list_top || row_top < list_bottom) {
      continue;
    }

    const bool is_selected = (row_index == rt->history_sel);

    /* Draw geometry follows the slide offset. */
    const float draw_top = row_top - slide;
    const float draw_bottom = row_bottom - slide;
    const float draw_center = row_center - slide;

    const float dim = locked ? 0.45f : 1.0f;
    if (checkpoints && is_armed) {
      /* Armed restore: accent wash + outline on the row itself, so the
       * second click has an unmistakable target. */
      rctf armed_rect;
      BLI_rctf_init(
          &armed_rect, row_xmin, row_xmax, draw_bottom + 2.0f * scale, draw_top - 2.0f * scale);
      float wash[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.16f * ease};
      float edge[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.55f * ease};
      chat_ui_draw_rounded_rect(&armed_rect, HIST_ROW_RADIUS * scale, wash);
      chat_ui_draw_rounded_rect_outline(&armed_rect, HIST_ROW_RADIUS * scale, edge, 1.0f);
    }
    else if (hit.is_hovered || is_selected) {
      rctf hover_rect;
      BLI_rctf_init(
          &hover_rect, row_xmin, row_xmax, draw_bottom + 2.0f * scale, draw_top - 2.0f * scale);
      float hover_col[4];
      chat_ui_get_history_row_hover_color(hover_col);
      hover_col[3] *= ease * (hit.is_hovered ? 1.0f : 0.7f);
      chat_ui_draw_rounded_rect(&hover_rect, HIST_ROW_RADIUS * scale, hover_col);
      if (is_selected) {
        /* Keyboard selection: accent outline so it reads distinctly from
         * a transient mouse hover. */
        float sel_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.45f * ease};
        chat_ui_draw_rounded_rect_outline(&hover_rect, HIST_ROW_RADIUS * scale, sel_col, 1.0f);
      }
    }

    /* Accent dot on the currently open chat. */
    if (is_current) {
      const float dot_r = HIST_DOT_RADIUS * scale;
      const float dot_cx = row_xmin + 13.0f * scale;
      rctf dot;
      BLI_rctf_init(&dot, dot_cx - dot_r, dot_cx + dot_r, draw_center - dot_r,
                    draw_center + dot_r);
      float dot_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], COL_ACCENT[3] * ease};
      chat_ui_draw_rounded_rect(&dot, dot_r, dot_col);
    }

    /* Time label, right-aligned before the X. An armed row shows a red
     * "Delete?" prompt instead — click the X again to confirm. A checkpoint
     * row's prompt names what the click does ("Revert turns 3–5?"). */
    const float del_zone_left = checkpoints ? row_xmax - 10.0f * scale :
                                              hit.delete_bounds.xmin - 8.0f * scale;
    const char *when_text = is_armed ?
                                (checkpoints ? (entry.action[0] ? entry.action : "Revert?") :
                                               "Delete?") :
                                entry.when;
    float when_w = 0.0f;
    if (when_text[0] != '\0') {
      when_w = hist_text_width(when_text, font_id, meta_px);
      float when_col[4];
      if (checkpoints && is_armed) {
        copy_v4_v4(when_col, COL_ACCENT);
        when_col[3] = ease * dim;
      }
      else if (is_armed) {
        copy_v4_v4(when_col, HIST_COL_DELETE_HOVER);
        when_col[3] *= ease;
      }
      else {
        copy_v4_v4(when_col, HIST_COL_MUTED);
        when_col[3] *= 0.95f * ease * dim;
      }
      hist_draw_label(when_text, font_id, meta_px, del_zone_left - when_w,
                      draw_center - float(meta_px) * 0.35f, when_col);
    }

    /* Title, ellipsis-clipped to the space before the time label. */
    {
      /* Checkpoints have no dot column. */
      const float title_x = row_xmin + (checkpoints ? HIST_CHECKPOINT_TITLE_INDENT :
                                                      HIST_TITLE_INDENT) * scale;
      const float title_max_w = (del_zone_left - when_w - 10.0f * scale) - title_x;
      char clipped[224];
      hist_text_ellipsis(entry.title[0] ? entry.title : (checkpoints ? "Checkpoint" : "Untitled chat"),
                         font_id, title_px, std::max(title_max_w, 20.0f * scale),
                         clipped, sizeof(clipped));
      const float *base_col = (is_current || (checkpoints && is_armed)) ? HIST_COL_TITLE_CURRENT :
                                                                          HIST_COL_TITLE;
      float title_col[4] = {base_col[0], base_col[1], base_col[2], base_col[3] * ease * dim};
      hist_draw_label(clipped, font_id, title_px, title_x,
                      draw_center - float(title_px) * 0.35f, title_col);
    }

    /* Delete X (ring + glyph). Armed rows keep a red-tinted ring and a red
     * glyph regardless of hover, signalling "click again to delete".
     * Checkpoint rows have no delete affordance. */
    if (!checkpoints) {
      if (is_armed || hit.delete_hovered) {
        rctf ring = hit.delete_bounds;
        ring.ymin -= slide;
        ring.ymax -= slide;
        const float *ring_base = is_armed ? HIST_COL_DELETE_ARMED_BG : HIST_COL_DELETE_HOVER_BG;
        float ring_col[4] = {ring_base[0], ring_base[1], ring_base[2], ring_base[3] * ease};
        chat_ui_draw_rounded_rect(&ring, del_half, ring_col);
      }
      const float *base_col = (is_armed || hit.delete_hovered) ? HIST_COL_DELETE_HOVER :
                                                                 HIST_COL_DELETE;
      float x_col[4] = {base_col[0], base_col[1], base_col[2], base_col[3] * ease};
      hist_draw_x_glyph(del_cx, draw_center, 4.2f * scale, x_col, scale);
    }
  }

  /* Restore the full-region scissor wm_draw_region_bind() established. */
  GPU_scissor(0, 0, winx, winy);

  /* Slim scrollbar thumb when the list overflows. */
  if (has_scrollbar) {
    const float track_top = list_top - 2.0f * scale;
    const float track_bottom = list_bottom + 2.0f * scale;
    const float track_h = track_top - track_bottom;
    if (track_h > 8.0f * scale) {
      const float thumb_h = std::max(track_h * view_h / content_h, 14.0f * scale);
      const float scroll_frac = (max_scroll > 0.0f) ? rt->history_scroll_px / max_scroll : 0.0f;
      const float thumb_top = track_top - (track_h - thumb_h) * scroll_frac - slide;
      rctf thumb;
      const float thumb_x = panel_x + panel_w - 7.0f * scale;
      BLI_rctf_init(&thumb, thumb_x, thumb_x + 3.5f * scale, thumb_top - thumb_h, thumb_top);
      float thumb_col[4] = {HIST_COL_SCROLL_THUMB[0], HIST_COL_SCROLL_THUMB[1],
                            HIST_COL_SCROLL_THUMB[2], HIST_COL_SCROLL_THUMB[3] * ease};
      chat_ui_draw_rounded_rect(&thumb, 1.75f * scale, thumb_col);
    }
  }

  GPU_blend(GPU_BLEND_NONE);
  UNUSED_VARS(any_hovered);
}

}  // namespace blender

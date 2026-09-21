/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "BLF_api.hh"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "DNA_screen_types.h"
#include "ED_mixar_glass.hh"
#include "GPU_state.hh"
#include "UI_interface.hh"
#include "mixie_chat_intern.hh"
#include "mixie_chat_rules_intern.hh"
#include <algorithm>
#include <cmath>
#include <cstring>

namespace blender {

void rules_draw_chrome(const RulesDrawFrame &f)
{
  const auto rt = f.rt;
  const auto &entries = f.entries;
  const auto font_id = f.font_id;
  const auto hint_px = f.hint_px;
  const auto header_px = f.header_px;
  const auto meta_px = f.meta_px;
  const auto winx = f.winx;
  const auto winy = f.winy;
  const auto scale = f.scale;
  const auto pad = f.pad;
  const auto header_h = f.header_h;
  const auto footer_h = f.footer_h;
  const auto mouse_x = f.mouse_x;
  const auto mouse_y = f.mouse_y;
  const auto slide = f.slide;
  const auto ease = f.ease;
  const auto radius = f.radius;
  const auto &panel = f.panel;

  /* Scrim. */
  {
    rctf full;
    BLI_rctf_init(&full, 0.0f, float(winx), 0.0f, float(winy));
    float scrim[4] = {
        HIST_COL_SCRIM[0], HIST_COL_SCRIM[1], HIST_COL_SCRIM[2], HIST_COL_SCRIM[3] * ease};
    chat_ui_draw_rounded_rect(&full, 0.0f, scrim);
  }

  /* Use the same liquid-glass material as the chat's floating cards. */
  rcti pane;
  BLI_rcti_rctf_copy(&pane, &panel);
  ui::MixarGlassStyle glass;
  glass.role = ui::MIXAR_GLASS_CARD;
  glass.radius = radius;
  glass.alpha = ease;
  glass.draw_shadow = true;
  ui::mixar_glass_draw(pane, glass);

  /* Header: title + count and close, with spacing instead of a divider. */
  {
    const float header_center = panel.ymax - header_h * 0.5f;
    const float baseline = header_center - float(header_px) * 0.35f;

    float title_col[4] = {HIST_COL_HEADER_TEXT[0],
                          HIST_COL_HEADER_TEXT[1],
                          HIST_COL_HEADER_TEXT[2],
                          HIST_COL_HEADER_TEXT[3] * ease};
    BLF_enable(font_id, BLF_BOLD);
    hist_draw_label("Project Rules", font_id, header_px, panel.xmin + pad, baseline, title_col);

    const float title_w = hist_text_width("Project Rules", font_id, header_px);
    BLF_disable(font_id, BLF_BOLD);

    if (!entries.is_empty()) {
      char count_buf[16];
      SNPRINTF(count_buf, "%d", int(entries.size()));
      float count_col[4] = {
          HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2], HIST_COL_MUTED[3] * ease};
      hist_draw_label(count_buf,
                      font_id,
                      meta_px,
                      panel.xmin + pad + title_w + 8.0f * scale,
                      header_center - float(meta_px) * 0.35f,
                      count_col);
    }

    /* Close X (ring on hover). */
    {
      const bool close_hovered = BLI_rctf_isect_pt(&rt->rules_close_bounds, mouse_x, mouse_y);
      const float close_cx = BLI_rctf_cent_x(&rt->rules_close_bounds);
      const float close_cy = BLI_rctf_cent_y(&rt->rules_close_bounds) - slide;
      if (close_hovered) {
        rctf ring = rt->rules_close_bounds;
        ring.ymin -= slide;
        ring.ymax -= slide;
        float ring_col[4] = {HIST_COL_DELETE_HOVER_BG[0],
                             HIST_COL_DELETE_HOVER_BG[1],
                             HIST_COL_DELETE_HOVER_BG[2],
                             HIST_COL_DELETE_HOVER_BG[3] * ease};
        chat_ui_draw_rounded_rect(&ring, HIST_CLOSE_SIZE * 0.5f * scale, ring_col);
      }
      float x_col[4] = {HIST_COL_MUTED[0],
                        HIST_COL_MUTED[1],
                        HIST_COL_MUTED[2],
                        (close_hovered ? 1.0f : 0.8f) * ease};
      if (close_hovered) {
        x_col[0] = HIST_COL_HEADER_TEXT[0];
        x_col[1] = HIST_COL_HEADER_TEXT[1];
        x_col[2] = HIST_COL_HEADER_TEXT[2];
      }
      hist_draw_x_glyph(close_cx, close_cy, 4.6f * scale, x_col, scale);
    }
  }

  /* Footer hint. */
  {
    const char *hint = "Enabled rules apply on your next message.";
    float hint_col[4] = {
        HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2], HIST_COL_MUTED[3] * 0.9f * ease};
    const float w = hist_text_width(hint, font_id, hint_px);
    const float cx = (panel.xmin + panel.xmax) * 0.5f;
    const float cy = panel.ymin + footer_h * 0.5f;
    hist_draw_label(hint, font_id, hint_px, cx - w * 0.5f, cy - float(hint_px) * 0.35f, hint_col);
  }
}
}  // namespace blender

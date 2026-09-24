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
static const float COL_ACCENT[4] = CHAT_ACCENT_LIVE;

void rules_draw_rows(const RulesDrawFrame &f)
{
  const auto rt = f.rt;
  const auto region = f.region;
  const auto &entries = f.entries;
  const auto &ditems = f.ditems;
  const auto &card_lines = f.card_lines;
  const auto font_id = f.font_id;
  const auto text_px = f.text_px;
  const auto hint_px = f.hint_px;
  const auto meta_px = f.meta_px;
  const auto scale = f.scale;
  const auto pad = f.pad;
  const auto line_h = f.line_h;
  const auto card_pad = f.card_pad;
  const auto indent = f.indent;
  const auto panel_x = f.panel_x;
  const auto panel_w = f.panel_w;
  const auto list_top = f.list_top;
  const auto list_bottom = f.list_bottom;
  const auto list_view_h = f.list_view_h;
  const auto list_content_h = f.list_content_h;
  const auto max_scroll = f.max_scroll;
  const auto mouse_x = f.mouse_x;
  const auto mouse_y = f.mouse_y;
  const auto slide = f.slide;
  const auto ease = f.ease;
  const auto &panel = f.panel;

  /* Rule cards, scissor-clipped to the list viewport. */
  if (entries.is_empty()) {
    float hint_col[4] = {
        HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2], HIST_COL_MUTED[3] * ease};
    const char *empty_text = "Add a rule above to guide Mixie.";
    const float w = hist_text_width(empty_text, font_id, meta_px);
    const float cx = (panel.xmin + panel.xmax) * 0.5f;
    hist_draw_label(empty_text,
                    font_id,
                    meta_px,
                    cx - w * 0.5f,
                    (list_top + list_bottom) * 0.5f - slide - float(meta_px) * 0.35f,
                    hint_col);
  }
  else {
    GPU_scissor(int(std::floor(panel_x)),
                int(std::floor(list_bottom)),
                int(std::ceil(panel_w)) + 1,
                int(std::ceil(list_view_h)) + 1);

    /* Section headers (draw-only rows of the display list). */
    for (const RulesDisplayItem &item : ditems) {
      if (item.entry >= 0) {
        continue;
      }
      const float item_top = list_top - item.top + rt->rules_scroll_px;
      const float item_bottom = item_top - item.height;
      if (item_bottom > list_top || item_top < list_bottom) {
        continue;
      }
      const float baseline = (item_top + item_bottom) * 0.5f - slide - float(hint_px) * 0.30f;
      float group_col[4] = {HIST_COL_MUTED[0],
                            HIST_COL_MUTED[1],
                            HIST_COL_MUTED[2],
                            HIST_COL_MUTED[3] * 0.9f * ease};
      hist_draw_label(
          item.label, font_id, hint_px, panel_x + pad + 8.0f * scale, baseline, group_col);
    }

    const bool in_list = BLI_rctf_isect_pt(&rt->rules_list_bounds, mouse_x, mouse_y);
    for (RuleRowHit &hit : rt->rules_rows) {
      hit.is_hovered = in_list && BLI_rctf_isect_pt(&hit.bounds, mouse_x, mouse_y);
      hit.toggle_hovered = hit.is_hovered &&
                           BLI_rctf_isect_pt(&hit.toggle_bounds, mouse_x, mouse_y);
      hit.edit_hovered = hit.is_hovered && BLI_rctf_isect_pt(&hit.edit_bounds, mouse_x, mouse_y);
      hit.scope_hovered = hit.is_hovered && BLI_rctf_isect_pt(&hit.scope_bounds, mouse_x, mouse_y);
      hit.delete_hovered = hit.is_hovered &&
                           BLI_rctf_isect_pt(&hit.delete_bounds, mouse_x, mouse_y);

      if (hit.bounds.ymin > list_top || hit.bounds.ymax < list_bottom) {
        continue; /* fully outside the viewport */
      }

      const RuleDrawEntry &entry = entries[hit.index];
      const bool is_editing = (hit.index == rt->rules_editing_index);
      const bool is_armed = (hit.index == rt->rules_confirm_delete);

      rctf card = hit.bounds;
      card.ymin -= slide;
      card.ymax -= slide;

      /* Card background (+hover wash, accent outline while being edited). */
      {
        rcti pane;
        BLI_rcti_rctf_copy(&pane, &card);
        ui::MixarGlassStyle glass;
        glass.role = ui::MIXAR_GLASS_CHAT;
        glass.radius = 10.0f * scale;
        glass.alpha = (hit.is_hovered ? 1.0f : 0.8f) * ease;
        ui::mixar_glass_draw(pane, glass);
        if (is_editing) {
          float outline[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.55f * ease};
          chat_ui_draw_rounded_rect_outline(&card, HIST_ROW_RADIUS * scale, outline, 1.0f);
        }
        else if (is_armed) {
          float outline[4] = {HIST_COL_DELETE_HOVER[0],
                              HIST_COL_DELETE_HOVER[1],
                              HIST_COL_DELETE_HOVER[2],
                              0.55f * ease};
          chat_ui_draw_rounded_rect_outline(&card, HIST_ROW_RADIUS * scale, outline, 1.0f);
        }
      }

      /* Enable/disable toggle pill: accent track + knob when on. */
      {
        rctf track = hit.toggle_bounds;
        track.ymin -= slide;
        track.ymax -= slide;
        const float knob_r = (track.ymax - track.ymin) * 0.5f - 1.5f * scale;
        float track_col[4];
        if (entry.enabled) {
          track_col[0] = COL_ACCENT[0] * 0.55f;
          track_col[1] = COL_ACCENT[1] * 0.55f;
          track_col[2] = COL_ACCENT[2] * 0.55f;
          track_col[3] = (hit.toggle_hovered ? 1.0f : 0.85f) * ease;
        }
        else {
          track_col[0] = 1.0f;
          track_col[1] = 1.0f;
          track_col[2] = 1.0f;
          track_col[3] = (hit.toggle_hovered ? 0.22f : 0.14f) * ease;
        }
        chat_ui_draw_rounded_rect(&track, (track.ymax - track.ymin) * 0.5f, track_col);

        rctf knob;
        const float cy = (track.ymin + track.ymax) * 0.5f;
        const float kx = entry.enabled ? track.xmax - 1.5f * scale - 2.0f * knob_r :
                                         track.xmin + 1.5f * scale;
        BLI_rctf_init(&knob, kx, kx + 2.0f * knob_r, cy - knob_r, cy + knob_r);
        float knob_col[4] = {0.95f, 0.97f, 1.0f, (entry.enabled ? 1.0f : 0.55f) * ease};
        chat_ui_draw_rounded_rect(&knob, knob_r, knob_col);
      }

      /* Edit (pencil) button under the toggle — the only way into edit
       * mode, so a stray click on the card body can't hijack the
       * composer. Accent glyph while this card is being edited. */
      {
        const float edit_cx = BLI_rctf_cent_x(&hit.edit_bounds);
        const float edit_cy = BLI_rctf_cent_y(&hit.edit_bounds) - slide;
        const float edit_half = RULES_EDIT_SIZE * 0.5f * scale;
        if (hit.edit_hovered) {
          rctf ring = hit.edit_bounds;
          ring.ymin -= slide;
          ring.ymax -= slide;
          float ring_col[4] = {HIST_COL_DELETE_HOVER_BG[0],
                               HIST_COL_DELETE_HOVER_BG[1],
                               HIST_COL_DELETE_HOVER_BG[2],
                               HIST_COL_DELETE_HOVER_BG[3] * ease};
          chat_ui_draw_rounded_rect(&ring, edit_half, ring_col);
        }
        float pen_col[4];
        if (is_editing) {
          pen_col[0] = COL_ACCENT[0];
          pen_col[1] = COL_ACCENT[1];
          pen_col[2] = COL_ACCENT[2];
          pen_col[3] = ease;
        }
        else {
          pen_col[0] = HIST_COL_MUTED[0];
          pen_col[1] = HIST_COL_MUTED[1];
          pen_col[2] = HIST_COL_MUTED[2];
          pen_col[3] = (hit.edit_hovered ? 1.0f : 0.8f) * ease;
        }
        rules_draw_edit_glyph(edit_cx, edit_cy, 4.6f * scale, pen_col, scale);
      }

      /* Show both destinations so changing scope is an explicit choice. */
      {
        rctf control = hit.scope_bounds;
        control.ymin -= slide;
        control.ymax -= slide;
        float caption_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2], ease};
        hist_draw_label("Applies to",
                        font_id,
                        meta_px,
                        control.xmin,
                        control.ymax + 4.0f * scale + line_h * 0.5f - float(meta_px) * 0.35f,
                        caption_col);
        const float radius = 6.0f * scale;
        float track_col[4] = {1.0f, 1.0f, 1.0f, 0.06f * ease};
        chat_ui_draw_rounded_rect(&control, radius, track_col);
        for (const bool global : {false, true}) {
          const rctf bounds = mixie_chat_rules_scope_choice_bounds(hit.scope_bounds, global);
          const bool selected = global == hit.is_global;
          const bool hovered = hit.scope_hovered && BLI_rctf_isect_pt(&bounds, mouse_x, mouse_y);
          rctf choice = bounds;
          choice.xmin += 2.0f * scale;
          choice.xmax -= 2.0f * scale;
          choice.ymin += 2.0f * scale - slide;
          choice.ymax -= 2.0f * scale + slide;
          if (selected || hovered) {
            float fill[4] = {selected ? COL_ACCENT[0] * 0.45f : 1.0f,
                             selected ? COL_ACCENT[1] * 0.45f : 1.0f,
                             selected ? COL_ACCENT[2] * 0.45f : 1.0f,
                             (selected ? 0.95f : 0.08f) * ease};
            chat_ui_draw_rounded_rect(&choice, radius - 2.0f * scale, fill);
          }
          const char *label = global ? RULES_SCOPE_GLOBAL : RULES_SCOPE_PROJECT;
          const float *base_col = selected ? HIST_COL_TITLE : HIST_COL_MUTED;
          float label_col[4] = {base_col[0], base_col[1], base_col[2], ease};
          const float width = hist_text_width(label, font_id, meta_px);
          hist_draw_label(label,
                          font_id,
                          meta_px,
                          BLI_rctf_cent_x(&choice) - width * 0.5f,
                          BLI_rctf_cent_y(&choice) - float(meta_px) * 0.35f,
                          label_col);
        }
      }

      /* Rule text (dimmed when disabled). */
      {
        const float *base_col = entry.enabled ? HIST_COL_TITLE : HIST_COL_MUTED;
        float col[4] = {base_col[0],
                        base_col[1],
                        base_col[2],
                        base_col[3] * (entry.enabled ? 1.0f : 0.8f) * ease};
        const float tx = hit.bounds.xmin + card_pad + indent;
        const float card_text_top = hit.bounds.ymax - card_pad;
        for (const RulesLineSpan &span : card_lines[hit.index]) {
          const float span_top = card_text_top - span.top * line_h - slide;
          const float baseline = span_top - line_h * 0.5f - float(text_px) * 0.35f;
          rules_draw_text_n(
              font_id, text_px, tx, baseline, col, entry.text + span.start, span.len);
        }
      }

      /* Delete X (arm-to-confirm, like history rows). */
      {
        const float del_cx = BLI_rctf_cent_x(&hit.delete_bounds);
        const float del_cy = BLI_rctf_cent_y(&hit.delete_bounds) - slide;
        const float del_half = HIST_DELETE_SIZE * 0.5f * scale;
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
        hist_draw_x_glyph(del_cx, del_cy, 4.2f * scale, x_col, scale);
      }
    }

    GPU_scissor(0, 0, region->winx, region->winy);

    /* Slim scrollbar thumb when the list overflows. */
    if (list_content_h > list_view_h + 0.5f) {
      const float track_top = list_top - 2.0f * scale;
      const float track_bottom = list_bottom + 2.0f * scale;
      const float track_h = track_top - track_bottom;
      if (track_h > 8.0f * scale) {
        const float thumb_h = std::max(track_h * list_view_h / list_content_h, 14.0f * scale);
        const float scroll_frac = (max_scroll > 0.0f) ? rt->rules_scroll_px / max_scroll : 0.0f;
        const float thumb_top = track_top - (track_h - thumb_h) * scroll_frac - slide;
        rctf thumb;
        const float thumb_x = panel_x + panel_w - 7.0f * scale;
        BLI_rctf_init(&thumb, thumb_x, thumb_x + 3.5f * scale, thumb_top - thumb_h, thumb_top);
        float thumb_col[4] = {HIST_COL_SCROLL_THUMB[0],
                              HIST_COL_SCROLL_THUMB[1],
                              HIST_COL_SCROLL_THUMB[2],
                              HIST_COL_SCROLL_THUMB[3] * ease};
        chat_ui_draw_rounded_rect(&thumb, 1.75f * scale, thumb_col);
      }
    }
  }
}
}  // namespace blender

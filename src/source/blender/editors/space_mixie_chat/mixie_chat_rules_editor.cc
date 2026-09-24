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
/** Length-bounded label draw (line spans are not null-terminated). */
void rules_draw_text_n(int font_id,
                       int font_px,
                       float x,
                       float baseline_y,
                       const float color[4],
                       const char *str,
                       int len)
{
  if (len <= 0) {
    return;
  }
  BLF_disable(font_id, BLF_CLIPPING);
  BLF_size(font_id, float(font_px));
  BLF_color4fv(font_id, color);
  BLF_position(font_id, x, baseline_y, 0.0f);
  BLF_draw(font_id, str, size_t(len));
  /* BLF can leave a different blend mode behind (see hist_draw_label). */
  GPU_blend(GPU_BLEND_ALPHA);
}

/** True when the composer holds something submittable. */
bool mixie_chat_rules_can_submit(const MixieChatRuntime *rt)
{
  for (const char *p = rt->rules_text; *p; p++) {
    if (*p != ' ' && *p != '\n' && *p != '\t') {
      return true;
    }
  }
  return false;
}

void rules_draw_editor(const RulesDrawFrame &f)
{
  const auto rt = f.rt;
  const auto region = f.region;
  const auto font_id = f.font_id;
  const auto text_px = f.text_px;
  const auto meta_px = f.meta_px;
  const auto scale = f.scale;
  const auto text_pad = f.text_pad;
  const auto line_h = f.line_h;
  const auto editor_inner_h = f.editor_inner_h;
  const auto mouse_x = f.mouse_x;
  const auto mouse_y = f.mouse_y;
  const auto slide = f.slide;
  const auto ease = f.ease;

  /* Composer / editor box. Accent outline while editing an existing rule
   * so the mode is unmistakable. */
  rctf field = rt->rules_text_bounds;
  field.ymin -= slide;
  field.ymax -= slide;
  const bool editing_existing = (rt->rules_editing_index >= 0);
  {
    rcti pane;
    BLI_rcti_rctf_copy(&pane, &field);
    ui::MixarGlassStyle glass;
    glass.role = ui::MIXAR_GLASS_CHAT;
    glass.radius = 10.0f * scale;
    glass.alpha = ease;
    ui::mixar_glass_draw(pane, glass);
    if (editing_existing) {
      float outline[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.55f * ease};
      chat_ui_draw_rounded_rect_outline(&field, 8.0f * scale, outline, 1.0f);
    }
    else {
      float outline[4] = {HIST_COL_SEARCH_OUTLINE[0],
                          HIST_COL_SEARCH_OUTLINE[1],
                          HIST_COL_SEARCH_OUTLINE[2],
                          HIST_COL_SEARCH_OUTLINE[3] * ease};
      chat_ui_draw_rounded_rect_outline(&field, 8.0f * scale, outline, 1.0f);
    }
  }

  const float text_x = field.xmin + text_pad;
  const float text_top = field.ymax - text_pad;
  const float text_bottom = field.ymin + text_pad;

  GPU_scissor(int(std::floor(field.xmin)),
              int(std::floor(text_bottom - 2.0f * scale)),
              int(std::ceil(field.xmax - field.xmin)) + 1,
              int(std::ceil(editor_inner_h + 4.0f * scale)) + 1);

  if (rt->rules_text[0] == '\0') {
    float hint_col[4] = {
        HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2], HIST_COL_MUTED[3] * 0.85f * ease};
    hist_draw_label("e.g. Use meters for all dimensions",
                    font_id,
                    text_px,
                    text_x + 3.0f * scale,
                    text_top - line_h * 0.5f - float(text_px) * 0.35f,
                    hint_col);
  }

  /* Selection range (anchor..cursor, either direction). */
  const int sel_from = (rt->rules_sel_anchor >= 0) ?
                           std::min(rt->rules_sel_anchor, rt->rules_cursor) :
                           -1;
  const int sel_to = (rt->rules_sel_anchor >= 0) ?
                         std::max(rt->rules_sel_anchor, rt->rules_cursor) :
                         -1;
  const bool has_selection = (sel_from >= 0 && sel_to > sel_from);

  float text_col[4] = {
      HIST_COL_TITLE[0], HIST_COL_TITLE[1], HIST_COL_TITLE[2], HIST_COL_TITLE[3] * ease};
  for (int li = 0; li < int(rt->rules_lines.size()); li++) {
    const RulesLineSpan &span = rt->rules_lines[li];
    const float span_top = text_top - span.top + rt->rules_editor_scroll;
    const float span_bottom = span_top - line_h;
    if (span_bottom > text_top || span_top < text_bottom) {
      continue;
    }
    /* Selection wash: the range's overlap with this line (partial at the
     * edge lines, full in between; a slim marker on empty lines). */
    if (has_selection && sel_to > span.start && sel_from <= span.start + span.len) {
      const int seg_from = std::max(sel_from, span.start);
      const int seg_to = std::min(sel_to, span.start + span.len);
      const float x1 = mixie_chat_rules_offset_to_x(rt, li, seg_from);
      float x2 = mixie_chat_rules_offset_to_x(rt, li, seg_to);
      if (x2 <= x1) {
        x2 = x1 + 4.0f * scale; /* empty line inside the selection */
      }
      rctf sel;
      BLI_rctf_init(&sel,
                    text_x + x1 - 1.0f * scale,
                    text_x + x2 + 1.0f * scale,
                    span_bottom + 1.5f * scale,
                    span_top - 1.5f * scale);
      float sel_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.22f * ease};
      chat_ui_draw_rounded_rect(&sel, 2.0f * scale, sel_col);
    }
    const float baseline = (span_top + span_bottom) * 0.5f - float(text_px) * 0.35f;
    rules_draw_text_n(
        font_id, text_px, text_x, baseline, text_col, rt->rules_text + span.start, span.len);
  }

  /* Caret. */
  {
    const int caret_line = mixie_chat_rules_line_of_offset(rt, rt->rules_cursor);
    if (caret_line < int(rt->rules_lines.size())) {
      const RulesLineSpan &span = rt->rules_lines[caret_line];
      const float caret_x = text_x +
                            mixie_chat_rules_offset_to_x(rt, caret_line, rt->rules_cursor);
      const float span_top = text_top - span.top + rt->rules_editor_scroll;
      const float cy = span_top - line_h * 0.5f;
      const float caret_half_h = float(text_px) * 0.62f;
      rctf caret;
      BLI_rctf_init(&caret, caret_x, caret_x + 1.5f * scale, cy - caret_half_h, cy + caret_half_h);
      float caret_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.9f * ease};
      chat_ui_draw_rounded_rect(&caret, 0.75f * scale, caret_col);
    }
  }

  GPU_scissor(0, 0, region->winx, region->winy);

  /* Submit button ("Add Rule" / "Save"), dimmed when nothing to submit. */
  {
    const bool can_submit = mixie_chat_rules_can_submit(rt);
    const bool submit_hovered = can_submit &&
                                BLI_rctf_isect_pt(&rt->rules_submit_bounds, mouse_x, mouse_y);
    rctf btn = rt->rules_submit_bounds;
    btn.ymin -= slide;
    btn.ymax -= slide;
    const float btn_alpha = (can_submit ? 1.0f : 0.45f) * ease;
    const float boost = submit_hovered ? 1.2f : 1.0f;
    float btn_col[4] = {0.094f * boost, 0.243f * boost, 0.145f * boost, btn_alpha};
    chat_ui_draw_rounded_rect(&btn, 10.0f * scale, btn_col);
    const char *label = editing_existing ? "Save" : "Add Rule";
    float label_col[4] = {0.94f, 0.96f, 0.95f, btn_alpha};
    BLF_enable(font_id, BLF_BOLD);
    const float label_w = hist_text_width(label, font_id, meta_px);
    hist_draw_label(label,
                    font_id,
                    meta_px,
                    (btn.xmin + btn.xmax) * 0.5f - label_w * 0.5f,
                    (btn.ymin + btn.ymax) * 0.5f - float(meta_px) * 0.35f,
                    label_col);
    BLF_disable(font_id, BLF_BOLD);
  }
}
}  // namespace blender

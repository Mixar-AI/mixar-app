/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Asset picker — the right-hand detail column for the selected pick,
 * built exactly like the Library's (`agent_ui_generations_detail.cc`):
 * a title padded down from the top, a preview plate that absorbs the spare
 * height, meta chips (library, match, kind), the name box, and the two
 * actions anchored to the panel's foot — green primary, grey secondary,
 * stacked when they do not fit side by side.
 *
 * The actions ANSWER the agent: "Use This Asset" sends the selected pick,
 * "Model from Scratch" the backend's own opt-out button. Both go through
 * `mixie_chat.select_slot_action`, so the chat records the answer, echoes it
 * as the user's message and resumes the turn exactly as a transcript click
 * would; the transcript returns by itself once the question is answered.
 */

#include "agent_ui_text.hh"

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "ED_mixie_chat_asset_picker.hh"

#include "agent_ui_asset_picker_intern.hh"
#include "agent_ui_generations_intern.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

void agent_ui_asset_picker_detail(const bContext *C,
                                  ui::Block *block,
                                  const rctf &panel,
                                  const PickFrame &frame,
                                  const MixieAssetPicker &picker)
{
  if (picker.count <= 0) {
    return;
  }
  MIXAR_THEME_LOAD(text, Text);
  MIXAR_THEME_LOAD(strong, TextStrong);
  const float meta_bg[4] = GEN_COL_META;
  const float plate[4] = GEN_COL_TILE;
  const float primary[4] = PANE_COL_GENERATE;
  const float secondary[4] = GEN_COL_SECONDARY;
  const float on_secondary[4] = {0.08f, 0.08f, 0.08f, 1.0f};

  const GenFrame &g = frame.gen;
  const float u = g.u;
  const float x0 = g.detail_x;
  const float col_w = g.detail_w;
  const float gap = g.block_gap;
  const int index = std::clamp(picker.selected, 0, picker.count - 1);
  const MixieAssetPick &pick = picker.picks[index];

  /* Title — the pick's rank, padded down from the panel top. */
  const float title_font = g.font_title;
  const float title_top = panel.ymax - std::max(GEN_TITLE_Y * u, g.pad);
  {
    char title[64];
    if (index == 0) {
      BLI_strncpy(title, "Best match", sizeof(title));
    }
    else {
      BLI_snprintf(title, sizeof(title), "Match %d of %d", index + 1, picker.count);
    }
    pane_fit_text(title, col_w, title_font);
    pane_label_left(title, x0, title_top - title_font * 0.5f, title_font, strong);
  }

  /* Actions anchor to the foot. */
  const float action_ymin = std::max(panel.ymin + GEN_DETAIL_FOOT * u, panel.ymin + g.pad);
  const float action_h = g.action_h;
  const float action_span = g.actions_stacked ? action_h * 2.0f + g.action_gap : action_h;
  const float action_top = action_ymin + action_span;

  /* Name box: the asset's own name, up to two lines. */
  const float meta_font = g.font_meta;
  const float meta_pad = gen_pad_px(u, meta_font);
  const float meta_h = gen_control_h(meta_font, meta_pad * 0.45f);
  char name_a[256];
  char name_b[256];
  agent_ui_asset_pick_wrap(
      pick.asset_name, std::max(1.0f, col_w - 2.0f * meta_pad), meta_font, name_a, name_b);
  const int name_lines = name_a[0] ? (name_b[0] ? 2 : 1) : 0;
  const float name_h = name_lines ? meta_pad * 0.7f +
                                        float(name_lines) * (meta_font + meta_pad * 0.35f) :
                                    0.0f;
  const float name_bottom = action_top + gap;
  const float name_top = name_bottom + name_h;

  /* Meta chips: library, match, kind — whichever exist, flowing onto a
   * second row instead of being dropped. */
  char match[32];
  agent_ui_asset_pick_match_label(pick, true, match);
  char kind[32];
  agent_ui_asset_pick_type_label(pick, kind);
  const char *meta_src[3] = {nullptr, nullptr, nullptr};
  int meta_count = 0;
  if (pick.library[0]) {
    meta_src[meta_count++] = pick.library;
  }
  if (match[0]) {
    meta_src[meta_count++] = match;
  }
  meta_src[meta_count++] = kind;

  const float meta_bottom = name_top + gap * 0.65f;
  float meta_rows_h = 0.0f;
  {
    float x = 0.0f;
    int rows = 1;
    for (int i = 0; i < meta_count; i++) {
      const float w = std::min(col_w, gen_control_w(pane_text_width(meta_src[i], meta_font), meta_pad));
      if (x > 0.0f && x + w > col_w) {
        rows++;
        x = 0.0f;
      }
      x += w + g.gap * 0.5f;
    }
    meta_rows_h = float(rows) * meta_h + float(rows - 1) * g.gap * 0.45f;
  }
  const float meta_top = meta_bottom + meta_rows_h;

  /* Preview absorbs whatever height is left, as in the Library. */
  rctf preview;
  preview.xmin = x0;
  preview.xmax = x0 + col_w;
  preview.ymax = title_top - title_font - gap;
  preview.ymin = std::max(meta_top + gap, preview.ymax - GEN_PREVIEW_H * u);
  if (BLI_rctf_size_y(&preview) >= std::max(GEN_PREVIEW_MIN * u, g.pad)) {
    pane_fill_round(&preview, std::min(GEN_TILE_RADIUS * u, g.pad), plate);
    agent_ui_asset_pick_thumb(C, pick, preview);
  }

  {
    float x = x0;
    float y_top = meta_top;
    for (int i = 0; i < meta_count; i++) {
      char label[256];
      BLI_strncpy(label, meta_src[i], sizeof(label));
      const float w = std::min(col_w, gen_control_w(pane_text_width(label, meta_font), meta_pad));
      if (x > x0 && x + w > x0 + col_w) {
        x = x0;
        y_top -= meta_h + g.gap * 0.45f;
      }
      rctf r;
      r.xmin = x;
      r.xmax = x + w;
      r.ymax = y_top;
      r.ymin = y_top - meta_h;
      pane_fill_round(&r, std::min(GEN_META_RADIUS * u, meta_h * 0.35f), meta_bg);
      pane_fit_text(label, std::max(1.0f, w - 2.0f * meta_pad), meta_font);
      pane_label_centre(label, BLI_rctf_cent_x(&r), BLI_rctf_cent_y(&r), meta_font, text);
      x = r.xmax + g.gap * 0.5f;
    }
  }

  if (name_lines) {
    rctf r;
    r.xmin = x0;
    r.xmax = x0 + col_w;
    r.ymax = name_top;
    r.ymin = name_bottom;
    pane_fill_round(&r, std::min(GEN_META_RADIUS * u, name_h * 0.35f), meta_bg);
    const float first_cy = r.ymax - meta_pad * 0.35f - meta_font * 0.5f;
    pane_label_left(name_a, x0 + meta_pad, first_cy, meta_font, text);
    if (name_b[0]) {
      pane_label_left(
          name_b, x0 + meta_pad, first_cy - (meta_font + meta_pad * 0.35f), meta_font, text);
    }
  }

  /* Actions: answer with the selected pick, or with the backend's opt-out. */
  struct Action {
    const char *label;
    const char *value;
    const char *tip;
  };
  const Action actions[2] = {
      {PICK_ACTION_PRIMARY, pick.value, "Append this asset from your library"},
      {PICK_ACTION_SECONDARY,
       picker.scratch_value,
       "Don't use a library asset — have the agent model it"},
  };
  for (int i = 0; i < 2; i++) {
    const bool enabled = actions[i].value && actions[i].value[0];
    rctf r;
    if (g.actions_stacked) {
      r.xmin = x0;
      r.xmax = x0 + g.action_w0;
      r.ymin = action_ymin + float(1 - i) * (action_h + g.action_gap);
      r.ymax = r.ymin + action_h;
    }
    else {
      const float width = (i == 0) ? g.action_w0 : g.action_w1;
      r.xmin = x0 + float(i) * (g.action_w0 + g.action_gap);
      r.xmax = r.xmin + width;
      r.ymin = action_ymin;
      r.ymax = action_ymin + action_h;
    }
    if (r.xmax > x0 + col_w) {
      r.xmax = x0 + col_w;
    }

    float fill[4];
    float label_col[4];
    memcpy(fill, i == 0 ? primary : secondary, sizeof(fill));
    memcpy(label_col, i == 0 ? strong : on_secondary, sizeof(label_col));
    if (!enabled) {
      fill[3] *= 0.35f;
      label_col[3] *= 0.5f;
    }
    pane_fill_round(&r, std::min(GEN_META_RADIUS * u, BLI_rctf_size_y(&r) * 0.35f), fill);
    char action_label[64];
    BLI_strncpy(action_label, actions[i].label, sizeof(action_label));
    pane_fit_text(action_label,
                  std::max(1.0f, BLI_rctf_size_x(&r) - 2.0f * gen_pad_px(u, g.font_action)),
                  g.font_action);
    pane_label_centre(
        action_label, BLI_rctf_cent_x(&r), BLI_rctf_cent_y(&r), g.font_action, label_col);
    if (enabled) {
      agent_ui_asset_pick_answer_button(block, r, picker, actions[i].value, actions[i].tip);
    }
  }
}

}  // namespace blender

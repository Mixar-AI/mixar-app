/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Library — the right-hand detail column: preview, metadata chips,
 * prompt, and the two actions the design gives every item.
 *
 * The actions are per-KIND and say what they will actually do, because the
 * four kinds sharing this grid cannot share one verb. A 3D asset goes into
 * the scene; a still or a movie goes onto the moodboard (there is no sane way
 * to drop a picture into a 3D scene, and a button that pretends otherwise is
 * worse than no button); a splat world is already in the file, so the useful
 * action is to select it; and a job that is still running has nothing to add
 * anywhere yet, so its primary reads as disabled and its secondary takes you
 * to the Queue tab.
 *
 * Every action is an operator that exists elsewhere: the ones in
 * `agent_bubble/ui/operators/generations_ops.py` and, for the Queue jump, the
 * same `wm.context_set_enum` the tab strip itself uses.
 */

#include "agent_ui_text.hh"

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_generations_intern.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** One action row: what it says, which operator runs it, and the string
 * properties that operator needs. An empty \a op means "draw it, but it
 * cannot be pressed" — the disabled state is a painted state, not a missing
 * button, so the column keeps its shape. */
struct ActionSpec {
  const char *label;
  const char *op;
  /* Up to three string properties — an append needs the .blend, the ID-type
   * folder inside it and the datablock's name, and none of the three can be
   * derived from the others on the Python side. */
  const char *prop[3];
  const char *value[3];
  const char *tip;
};

/** Break \a text into at most two lines that each fit \a max_w, at word
 * boundaries where possible. The second line takes an ellipsis when the text
 * runs past it. */
void wrap_two_lines(
    const char *text, const float max_w, const float font, char r_a[160], char r_b[160])
{
  r_a[0] = '\0';
  r_b[0] = '\0';
  if (!text || !text[0]) {
    return;
  }
  BLI_strncpy(r_a, text, 160);
  if (pane_text_width(r_a, font) <= max_w) {
    return;
  }
  /* Longest prefix ending on a space or filename punctuation that still
   * fits, so a long asset name wraps instead of becoming one ellipsis. */
  int split = 0;
  for (int i = 0; r_a[i]; i++) {
    const char ch = r_a[i];
    if (ch != ' ' && ch != '-' && ch != '_' && ch != '.') {
      continue;
    }
    char probe[160];
    /* Keep the punctuation on the first line; a space is not part of it. */
    BLI_strncpy(probe, r_a, size_t(i) + (ch == ' ' ? 1 : 2));
    if (pane_text_width(probe, font) > max_w) {
      break;
    }
    split = i;
  }
  if (split == 0) {
    /* One unbreakable run — let the fitter cut it mid-word.
     *
     * `pane_fit_text` appends a 3-byte U+2026 at the cut, so `strlen(r_a)` is
     * NOT how many bytes of `text` it consumed: resuming the second line at
     * `text + strlen(r_a)` skipped three real bytes and, when those bytes sat
     * inside a multi-byte character, started the tail mid-sequence and drew
     * mojibake. Subtract the ellipsis to get the true head length. */
    pane_fit_text(r_a, 160, max_w, font);
    static const char ELLIPSIS[] = "\xE2\x80\xA6"; /* U+2026, as pane_fit_text writes */
    const size_t ellipsis_len = sizeof(ELLIPSIS) - 1;
    size_t head = strlen(r_a);
    if (head >= ellipsis_len && STREQ(r_a + head - ellipsis_len, ELLIPSIS)) {
      head -= ellipsis_len;
    }
    BLI_strncpy(r_b, text + head, 160);
  }
  else {
    BLI_strncpy(r_b, r_a + split + 1, 160);
    if (r_a[split] == ' ') {
      r_a[split] = '\0';
    }
    else {
      r_a[split + 1] = '\0';
    }
  }
  pane_fit_text(r_b, 160, max_w, font);
}

/** Sketch and Voice lock every tab change, including this column's Queue jump. */
bool tabs_locked(const bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return false;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  auto armed = [&](const char *name) -> bool {
    PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, name);
    return prop != nullptr && RNA_property_boolean_get(&wm_ptr, prop);
  };
  return armed("mixar_mark_armed") || armed("mixie_chat_voice_listening");
}

/** The chip row under the preview: whichever of model / age / kind exist. */
int build_meta(const GenItem &item, const char *(&r_chips)[3])
{
  int n = 0;
  if (item.model_label[0]) {
    r_chips[n++] = item.model_label;
  }
  if (item.age[0] && n < 3) {
    r_chips[n++] = item.age;
  }
  if (item.type_label[0] && n < 3) {
    r_chips[n++] = item.type_label;
  }
  return n;
}

void build_actions(const GenItem &item, ActionSpec r_actions[2])
{
  r_actions[0] = ActionSpec{};
  r_actions[1] = ActionSpec{};

  switch (item.kind) {
    case GEN_ITEM_ASSET:
      r_actions[0] = {"Add to Scene",
                      "mixar.generations_add_asset",
                      {"blend_path", "id_dir", "asset_name"},
                      {item.path, item.id_dir, item.name},
                      "Append this asset into the current scene"};
      r_actions[1] = {"Open Folder",
                      item.path[0] ? "mixar.generations_open_folder" : "",
                      {"path", nullptr, nullptr},
                      {item.path, nullptr, nullptr},
                      "Show the asset's .blend in the file browser"};
      break;
    case GEN_ITEM_IMAGE:
    case GEN_ITEM_VIDEO:
      /* The image is already on the board — that is where this pane found
       * it — so the useful verb is "select", which is how the board's
       * selection becomes a reference everywhere else. */
      r_actions[0] = {"Select on Board",
                      "mixar.generations_select_media",
                      {"image_name", nullptr, nullptr},
                      {item.name, nullptr, nullptr},
                      "Select this on the moodboard so it can be used as a reference"};
      r_actions[1] = {"Open Folder",
                      item.path[0] ? "mixar.generations_open_folder" : "",
                      {"path", nullptr, nullptr},
                      {item.path, nullptr, nullptr},
                      "Show this file in the file browser"};
      break;
    case GEN_ITEM_SPLAT:
      r_actions[0] = {"Select in Scene",
                      "mixar.generations_select_splat",
                      {"collection_name", nullptr, nullptr},
                      {item.name, nullptr, nullptr},
                      "Select this splat world's handle in the viewport"};
      r_actions[1] = {"Already in file", "", {nullptr, nullptr, nullptr},
                      {nullptr, nullptr, nullptr}, ""};
      break;
    case GEN_ITEM_JOB:
      r_actions[0] = {"Generating…", "", {nullptr, nullptr, nullptr},
                      {nullptr, nullptr, nullptr}, ""};
      r_actions[1] = {"Open Queue", "", {nullptr, nullptr, nullptr},
                      {nullptr, nullptr, nullptr}, ""};
      break;
  }
}

}  // namespace

void agent_ui_generations_detail(const bContext *C,
                                 ui::Block *block,
                                 const rctf &panel,
                                 const GenFrame &frame,
                                 const GenPaneData &data)
{
  MIXAR_THEME_LOAD(text, Text);
  MIXAR_THEME_LOAD(strong, TextStrong);
  MIXAR_THEME_LOAD(dim, TextSecondary);
  const float meta_bg[4] = GEN_COL_META;
  const float plate[4] = GEN_COL_TILE;
  const float primary[4] = PANE_COL_GENERATE;
  const float secondary[4] = GEN_COL_SECONDARY;
  const float on_secondary[4] = {0.08f, 0.08f, 0.08f, 1.0f};
  const float u = frame.u;

  const float x0 = frame.detail_x;
  const float col_w = frame.detail_w;
  const float gap = frame.block_gap;

  const int index = agent_ui_generations_selected_index(data);
  if (index < 0) {
    pane_label_centre(data.count > 0 ? "Select a generation" : "Nothing selected",
                      x0 + col_w * 0.5f,
                      (panel.ymin + panel.ymax) * 0.5f,
                      frame.font_meta,
                      dim);
    return;
  }
  const GenItem &item = data.items[index];

  /* Title — padded down from the panel top, fitted to the column. */
  const float title_font = frame.font_title;
  const float title_top = panel.ymax - std::max(GEN_TITLE_Y * u, frame.pad);
  {
    char title[96];
    BLI_strncpy(title, item.type_label[0] ? item.type_label : item.name, sizeof(title));
    pane_fit_text(title, col_w, title_font);
    pane_label_left(title, x0, title_top - title_font * 0.5f, title_font, strong);
  }

  /* Actions anchor to the foot. Stacked buttons each get a padded row;
   * side by side they share the column with a gap between them. */
  const float action_ymin = std::max(panel.ymin + GEN_DETAIL_FOOT * u, panel.ymin + frame.pad);
  const float action_h = frame.action_h;
  const float action_span = frame.actions_stacked ? action_h * 2.0f + frame.action_gap : action_h;
  const float action_top = action_ymin + action_span;

  const float desc_font = frame.font_desc;
  const float desc_pitch = std::max(GEN_DESC_PITCH * u, desc_font + frame.gap * 0.35f);
  char line_a[160];
  char line_b[160];
  const bool detail_is_name = item.detail[0] && STREQ(item.detail, item.name);
  wrap_two_lines(detail_is_name ? "" : item.detail, col_w, desc_font, line_a, line_b);
  const int desc_lines = line_a[0] ? (line_b[0] ? 2 : 1) : 0;
  const float desc_bottom = action_top + (desc_lines ? gap : 0.0f);
  const float desc_top = desc_bottom + float(desc_lines) * desc_pitch;

  const float meta_font = frame.font_meta;
  const float meta_pad = gen_pad_px(u, meta_font);
  const float meta_h = gen_control_h(meta_font, meta_pad * 0.45f);
  char name_a[160];
  char name_b[160];
  wrap_two_lines(item.name, std::max(1.0f, col_w - 2.0f * meta_pad), meta_font, name_a, name_b);
  const int name_lines = name_a[0] ? (name_b[0] ? 2 : 1) : 0;
  const float name_h = name_lines ? meta_pad * 0.7f + float(name_lines) * (meta_font + meta_pad * 0.35f) :
                                    0.0f;
  const float name_bottom = (desc_lines ? desc_top : action_top) + gap;
  const float name_top = name_bottom + name_h;

  const char *meta_src[3] = {nullptr, nullptr, nullptr};
  const int meta_count = build_meta(item, meta_src);
  const float meta_bottom = name_top + (meta_count ? gap * 0.65f : 0.0f);
  /* Chips flow onto a second row instead of being dropped. */
  float meta_rows_h = 0.0f;
  if (meta_count) {
    float x = 0.0f;
    int rows = 1;
    for (int i = 0; i < meta_count; i++) {
      const float w = gen_control_w(pane_text_width(meta_src[i], meta_font), meta_pad);
      if (x > 0.0f && x + w > col_w) {
        rows++;
        x = 0.0f;
      }
      x += w + frame.gap * 0.5f;
    }
    meta_rows_h = float(rows) * meta_h + float(rows - 1) * frame.gap * 0.45f;
  }
  const float meta_top = meta_bottom + meta_rows_h;

  rctf preview;
  preview.xmin = x0;
  preview.xmax = x0 + col_w;
  preview.ymax = title_top - title_font - gap;
  preview.ymin = std::max(meta_top + gap, preview.ymax - GEN_PREVIEW_H * u);
  if (BLI_rctf_size_y(&preview) >= std::max(GEN_PREVIEW_MIN * u, frame.pad)) {
    pane_fill_round(&preview, std::min(GEN_TILE_RADIUS * u, frame.pad), plate);
    agent_ui_generations_thumb(C, item, preview, u);
  }

  if (meta_count) {
    float x = x0;
    float y_top = meta_top;
    for (int i = 0; i < meta_count; i++) {
      char label[64];
      BLI_strncpy(label, meta_src[i], sizeof(label));
      const float w = std::min(col_w, gen_control_w(pane_text_width(label, meta_font), meta_pad));
      if (x > x0 && x + w > x0 + col_w) {
        x = x0;
        y_top -= meta_h + frame.gap * 0.45f;
      }
      rctf r;
      r.xmin = x;
      r.xmax = x + w;
      r.ymax = y_top;
      r.ymin = y_top - meta_h;
      pane_fill_round(&r, std::min(GEN_META_RADIUS * u, meta_h * 0.35f), meta_bg);
      pane_fit_text(label, std::max(1.0f, w - 2.0f * meta_pad), meta_font);
      pane_label_centre(label, BLI_rctf_cent_x(&r), BLI_rctf_cent_y(&r), meta_font, text);
      x = r.xmax + frame.gap * 0.5f;
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
      pane_label_left(name_b,
                      x0 + meta_pad,
                      first_cy - (meta_font + meta_pad * 0.35f),
                      meta_font,
                      text);
    }
  }

  if (desc_lines) {
    const float first_cy = desc_top - desc_pitch * 0.5f;
    pane_label_left(line_a, x0, first_cy, desc_font, dim);
    if (line_b[0]) {
      pane_label_left(line_b, x0, first_cy - desc_pitch, desc_font, dim);
    }
  }

  /* Actions. */
  ActionSpec actions[2];
  build_actions(item, actions);
  for (int i = 0; i < 2; i++) {
    if (!actions[i].label || !actions[i].label[0]) {
      continue;
    }
    const bool enabled = (actions[i].op && actions[i].op[0]) ||
                         (item.kind == GEN_ITEM_JOB && i == 1);
    rctf r;
    if (frame.actions_stacked) {
      r.xmin = x0;
      r.xmax = x0 + frame.action_w0;
      r.ymin = action_ymin + float(1 - i) * (action_h + frame.action_gap);
      r.ymax = r.ymin + action_h;
    }
    else {
      const float width = (i == 0) ? frame.action_w0 : frame.action_w1;
      r.xmin = x0 + float(i) * (frame.action_w0 + frame.action_gap);
      r.xmax = r.xmin + width;
      r.ymin = action_ymin;
      r.ymax = action_ymin + action_h;
    }
    if (r.xmax > x0 + col_w) {
      r.xmax = x0 + col_w;
    }

    float fill[4];
    float label_col[4];
    if (i == 0) {
      memcpy(fill, primary, sizeof(fill));
      memcpy(label_col, strong, sizeof(label_col));
    }
    else {
      memcpy(fill, secondary, sizeof(fill));
      memcpy(label_col, on_secondary, sizeof(label_col));
    }
    if (!enabled) {
      fill[3] *= 0.35f;
      label_col[3] *= 0.5f;
    }
    pane_fill_round(&r, std::min(GEN_META_RADIUS * u, BLI_rctf_size_y(&r) * 0.35f), fill);
    char action_label[64];
    BLI_strncpy(action_label, actions[i].label, sizeof(action_label));
    pane_fit_text(action_label,
                  std::max(1.0f, BLI_rctf_size_x(&r) - 2.0f * gen_pad_px(u, frame.font_action)),
                  frame.font_action);
    pane_label_centre(action_label,
                      BLI_rctf_cent_x(&r),
                      BLI_rctf_cent_y(&r),
                      frame.font_action,
                      label_col);

    if (!enabled) {
      continue;
    }
    if (item.kind == GEN_ITEM_JOB && i == 1) {
      /* Jump to the Queue tab — the same stock operator the tab strip uses,
       * so there is exactly one way the island changes tabs. While sketching
       * or dictating that jump is the same refusal as the strip. */
      const bool locked = tabs_locked(C);
      ui::Button *but = uiDefButO(block, ui::ButtonType::But,
                             locked ? "mixar.bubble_tab_locked" : "wm.context_set_enum",
                             blender::wm::OpCallContext::InvokeDefault, "",
                             int(r.xmin), int(r.ymin), short(BLI_rctf_size_x(&r)),
                             short(BLI_rctf_size_y(&r)),
                             locked ? "Finish sketching or dictating before switching tabs" :
                                      "Show the generation queue");
      if (but && !locked) {
        PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
        RNA_string_set(op_ptr, "data_path", "window_manager.mixar_bubble_tab");
        RNA_string_set(op_ptr, "value", "QUEUE");
      }
      continue;
    }
    ui::Button *but = uiDefButO(block, ui::ButtonType::But, actions[i].op,
                           blender::wm::OpCallContext::InvokeDefault, "",
                           int(r.xmin), int(r.ymin), short(BLI_rctf_size_x(&r)),
                           short(BLI_rctf_size_y(&r)), actions[i].tip);
    if (but) {
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
      for (int p = 0; p < 3; p++) {
        if (actions[i].prop[p] && actions[i].prop[p][0]) {
          RNA_string_set(op_ptr, actions[i].prop[p],
                         actions[i].value[p] ? actions[i].value[p] : "");
        }
      }
    }
  }
  UNUSED_VARS(C);
}

}  // namespace blender

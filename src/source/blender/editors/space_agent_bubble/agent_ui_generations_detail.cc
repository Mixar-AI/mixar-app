/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * My Generations — the right-hand detail column: preview, metadata chips,
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

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"

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
  /* Longest prefix ending on a space that still fits. */
  int split = 0;
  for (int i = 0; r_a[i]; i++) {
    if (r_a[i] != ' ') {
      continue;
    }
    char probe[160];
    BLI_strncpy(probe, r_a, size_t(i) + 1);
    if (pane_text_width(probe, font) > max_w) {
      break;
    }
    split = i;
  }
  if (split == 0) {
    /* One unbreakable run — let the fitter cut it mid-word. */
    pane_fit_text(r_a, max_w, font);
    BLI_strncpy(r_b, text + strlen(r_a), 160);
  }
  else {
    BLI_strncpy(r_b, r_a + split + 1, 160);
    r_a[split] = '\0';
  }
  pane_fit_text(r_b, max_w, font);
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
                                 const float u,
                                 const GenPaneData &data)
{
  const float text[4] = AGENT_COL_TEXT;
  const float strong[4] = AGENT_COL_TEXT_STRONG;
  const float dim[4] = AGENT_COL_TEXT_DIM;
  const float meta_bg[4] = GEN_COL_META;
  const float plate[4] = GEN_COL_TILE;
  const float primary[4] = PANE_COL_GENERATE;
  const float secondary[4] = GEN_COL_SECONDARY;
  const float on_secondary[4] = {0.08f, 0.08f, 0.08f, 1.0f};

  const float x0 = GEN_XL(panel, GEN_DETAIL_X, u);
  const float col_w = GEN_DETAIL_W * u;

  const int index = agent_ui_generations_selected_index(data);
  if (index < 0) {
    pane_label_centre(data.count > 0 ? "Select a generation" : "Nothing selected",
                      x0 + col_w * 0.5f,
                      (panel.ymin + panel.ymax) * 0.5f,
                      GEN_META_FONT * u,
                      dim);
    return;
  }
  const GenItem &item = data.items[index];

  /* Title — the item's kind, as the design heads the column. */
  {
    char title[96];
    BLI_strncpy(title, item.type_label[0] ? item.type_label : item.name, sizeof(title));
    pane_fit_text(title, col_w, GEN_TITLE_FONT * u);
    pane_label_left(title,
                    x0,
                    GEN_YTOP(panel, GEN_TITLE_Y, u) - GEN_TITLE_FONT * u * 0.5f,
                    GEN_TITLE_FONT * u,
                    strong);
  }

  /* The stack below the preview is measured UP from the panel's foot (see
   * GEN_DETAIL_FOOT): actions, then the prompt, then the two chip rows. */
  const float action_ymin = panel.ymin + GEN_DETAIL_FOOT * u;
  const float action_ymax = action_ymin + GEN_ACTION_H * u;

  const float desc_font = GEN_DESC_FONT * u;
  char line_a[160];
  char line_b[160];
  wrap_two_lines(item.detail, col_w, desc_font, line_a, line_b);
  const int desc_lines = line_a[0] ? (line_b[0] ? 2 : 1) : 0;
  const float desc_bottom = action_ymax + GEN_DETAIL_GAP * u;
  const float desc_top = desc_bottom + float(desc_lines) * GEN_DESC_PITCH * u;

  /* Rows stack UPWARD from here, so each one's ymin is the previous row's
   * ymax plus the gap — the name chip sits above the prompt and the
   * model/age/kind row above that, matching the design's order top-down. */
  const float meta2_ymin = (desc_lines ? desc_top : action_ymax + GEN_DETAIL_GAP * u) +
                           GEN_DETAIL_GAP * u;
  const float meta2_ymax = meta2_ymin + GEN_META_H * u;
  const float meta1_ymin = meta2_ymax + GEN_META_ROW_GAP * u;
  const float meta1_ymax = meta1_ymin + GEN_META_H * u;

  /* Preview: keeps the design's top anchor and gives the rest of its height
   * to whatever room is left above the chips. */
  rctf preview;
  preview.xmin = x0;
  preview.xmax = std::min(x0 + GEN_PREVIEW_W * u, panel.xmax - GEN_PAD * u);
  preview.ymax = GEN_YTOP(panel, GEN_PREVIEW_Y, u);
  preview.ymin = std::max(meta1_ymin + GEN_DETAIL_GAP * u,
                          preview.ymax - GEN_PREVIEW_H * u);
  if (BLI_rctf_size_y(&preview) >= GEN_PREVIEW_MIN * u) {
    pane_fill_round(&preview, GEN_TILE_RADIUS * u, plate);
    agent_ui_generations_thumb(C, item, preview, u);
  }

  /* Metadata chips: model / age / kind, then the item's own name on the row
   * below (the design's second, shorter chip). */
  {
    const char *chips[3] = {nullptr, nullptr, nullptr};
    const int chip_count = build_meta(item, chips);
    float x = x0;
    const float font = GEN_META_FONT * u;
    for (int i = 0; i < chip_count; i++) {
      char label[64];
      BLI_strncpy(label, chips[i], sizeof(label));
      const float w = pane_text_width(label, font) + 2.0f * GEN_META_PAD_X * u;
      if (x + w > x0 + col_w) {
        break;
      }
      rctf r;
      r.xmin = x;
      r.xmax = x + w;
      r.ymax = meta1_ymax;
      r.ymin = meta1_ymin;
      pane_fill_round(&r, GEN_META_RADIUS * u, meta_bg);
      pane_label_centre(label, BLI_rctf_cent_x(&r), BLI_rctf_cent_y(&r), font, text);
      x = r.xmax + GEN_META_GAP * u;
    }

    char name[96];
    BLI_strncpy(name, item.name, sizeof(name));
    pane_fit_text(name, col_w - 2.0f * GEN_META_PAD_X * u, font);
    rctf r;
    r.xmin = x0;
    r.xmax = x0 + pane_text_width(name, font) + 2.0f * GEN_META_PAD_X * u;
    r.ymax = meta2_ymax;
    r.ymin = meta2_ymin;
    pane_fill_round(&r, GEN_META_RADIUS * u, meta_bg);
    pane_label_centre(name, BLI_rctf_cent_x(&r), BLI_rctf_cent_y(&r), font, text);
  }

  /* Prompt / description, wrapped to at most two lines. */
  if (desc_lines) {
    const float first_cy = desc_top - GEN_DESC_PITCH * u * 0.5f;
    pane_label_left(line_a, x0, first_cy, desc_font, dim);
    if (line_b[0]) {
      pane_label_left(line_b, x0, first_cy - GEN_DESC_PITCH * u, desc_font, dim);
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
    r.xmin = x0 + float(i) * (GEN_ACTION_W + GEN_ACTION_GAP) * u;
    r.xmax = r.xmin + GEN_ACTION_W * u;
    r.ymax = action_ymax;
    r.ymin = action_ymin;
    if (r.xmax > panel.xmax - GEN_PAD * u) {
      r.xmax = panel.xmax - GEN_PAD * u;
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
    pane_fill_round(&r, GEN_META_RADIUS * u, fill);
    pane_label_centre(actions[i].label,
                      BLI_rctf_cent_x(&r),
                      BLI_rctf_cent_y(&r),
                      GEN_ACTION_FONT * u,
                      label_col);

    if (!enabled) {
      continue;
    }
    if (item.kind == GEN_ITEM_JOB && i == 1) {
      /* Jump to the Queue tab — the same stock operator the tab strip uses,
       * so there is exactly one way the island changes tabs. */
      ui::Button *but = uiDefButO(block, ui::ButtonType::But, "wm.context_set_enum",
                             blender::wm::OpCallContext::InvokeDefault, "",
                             int(r.xmin), int(r.ymin), short(BLI_rctf_size_x(&r)),
                             short(BLI_rctf_size_y(&r)), "Show the generation queue");
      if (but) {
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

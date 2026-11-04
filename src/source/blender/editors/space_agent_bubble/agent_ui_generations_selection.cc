/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The Library pane's selection: one ACTIVE key (`mixar_generations_selected`,
 * what the detail column describes) plus, after a Ctrl/Cmd/Shift-click, the
 * whole set (`mixar_generations_multi`, newline-joined). Both are written by
 * `mixar.generations_select` in `agent_bubble/ui/operators/generations_ops.py`;
 * the pane only reads them.
 */

#include <algorithm>
#include <cstring>
#include <utility>
#include <string>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "WM_types.hh"

#include "agent_ui_generations_intern.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_text.hh"
#include "agent_ui_theme.hh"

namespace blender {

void agent_ui_generations_read_multi(PointerRNA *wm_ptr, GenPaneData *data)
{
  data->multi.clear();
  PropertyRNA *prop = RNA_struct_find_property(wm_ptr, "mixar_generations_multi");
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return;
  }
  const std::string multi = RNA_property_string_get(wm_ptr, prop);
  size_t start = 0;
  while (start < multi.size()) {
    const size_t end = std::min(multi.find('\n', start), multi.size());
    if (end > start) {
      data->multi.emplace_back(multi, start, end - start);
    }
    start = end + 1;
  }
}

bool agent_ui_generations_is_selected(const GenPaneData &data, const char *key)
{
  if (!key || !key[0]) {
    return false;
  }
  if (STREQ(data.selected, key)) {
    return true;
  }
  return std::find(data.multi.begin(), data.multi.end(), key) != data.multi.end();
}

namespace {

struct MultiCounts {
  int images = 0, videos = 0, assets = 0, other = 0;
  int addable() const
  {
    return images + videos + assets;
  }
};

/** What the selection holds. A key hidden by the current filter still counts:
 * its prefix says whether "Add" can act on it. */
MultiCounts count_selection(const GenPaneData &data)
{
  MultiCounts counts;
  for (const std::string &key : data.multi) {
    const GenItem *item = nullptr;
    for (const GenItem &candidate : data.items) {
      if (key == candidate.key) {
        item = &candidate;
        break;
      }
    }
    if (item && gen_item_is_file(*item)) {
      (item->kind == GEN_ITEM_VIDEO ? counts.videos : counts.images)++;
    }
    else if (key.rfind("asset:", 0) == 0) {
      counts.assets++;
    }
    else if (key.rfind("file:", 0) == 0) {
      counts.images++;
    }
    else {
      counts.other++;
    }
  }
  return counts;
}

void action_button(ui::Block *block,
                   const rctf &r,
                   const GenFrame &frame,
                   const char *label,
                   const char *op,
                   const bool primary,
                   const bool enabled,
                   const char *tip)
{
  MIXAR_THEME_LOAD(strong, TextStrong);
  float fill[4] = GEN_COL_SECONDARY;
  float ink[4] = {0.08f, 0.08f, 0.08f, 1.0f};
  if (primary) {
    const float generate[4] = PANE_COL_GENERATE;
    memcpy(fill, generate, sizeof(fill));
    memcpy(ink, strong, sizeof(ink));
  }
  if (!enabled) {
    fill[3] *= 0.35f;
    ink[3] *= 0.5f;
  }
  pane_fill_round(&r, std::min(GEN_META_RADIUS * frame.u, BLI_rctf_size_y(&r) * 0.35f), fill);
  char text[64];
  BLI_strncpy(text, label, sizeof(text));
  pane_fit_text(text,
                std::max(1.0f, BLI_rctf_size_x(&r) - 2.0f * gen_pad_px(frame.u, frame.font_action)),
                frame.font_action);
  pane_label_centre(text, BLI_rctf_cent_x(&r), BLI_rctf_cent_y(&r), frame.font_action, ink);
  if (enabled) {
    uiDefButO(block,
              ui::ButtonType::But,
              op,
              wm::OpCallContext::InvokeDefault,
              "",
              int(r.xmin),
              int(r.ymin),
              short(BLI_rctf_size_x(&r)),
              short(BLI_rctf_size_y(&r)),
              tip);
  }
}

}  // namespace

void agent_ui_generations_detail_multi(ui::Block *block,
                                       const rctf &panel,
                                       const GenFrame &frame,
                                       const GenPaneData &data)
{
  MIXAR_THEME_LOAD(strong, TextStrong);
  MIXAR_THEME_LOAD(dim, TextSecondary);
  const float x0 = frame.detail_x;
  const float col_w = frame.detail_w;
  const float u = frame.u;
  const MultiCounts counts = count_selection(data);

  char line[96];
  const float title_top = panel.ymax - std::max(GEN_TITLE_Y * u, frame.pad);
  BLI_snprintf(line, sizeof(line), "%d selected", int(data.multi.size()));
  pane_fit_text(line, col_w, frame.font_title);
  pane_label_left(line, x0, title_top - frame.font_title * 0.5f, frame.font_title, strong);

  /* One line per kind, under the title. */
  const float pitch = frame.font_desc * 1.5f;
  float cy = title_top - frame.font_title - frame.block_gap - frame.font_desc * 0.5f;
  const std::pair<int, const char *> rows[] = {
      {counts.images, "image"}, {counts.videos, "video"}, {counts.assets, "3D asset"},
      {counts.other, "item already in Mixar"}};
  for (const auto &[n, noun] : rows) {
    if (n == 0) {
      continue;
    }
    BLI_snprintf(line, sizeof(line), "%d %s%s", n, noun, n == 1 ? "" : "s");
    pane_fit_text(line, col_w, frame.font_desc);
    pane_label_left(line, x0, cy, frame.font_desc, dim);
    cy -= pitch;
  }
  cy -= frame.block_gap * 0.5f;
  const char *notes[] = {"Images & videos go to the moodboard.", "3D assets go into the scene."};
  for (const char *note : notes) {
    BLI_strncpy(line, note, sizeof(line));
    pane_fit_text(line, col_w, frame.font_desc);
    pane_label_left(line, x0, cy, frame.font_desc, dim);
    cy -= pitch;
  }

  /* Actions stacked at the foot, like the single-item column. */
  const float h = frame.action_h;
  const float w = std::min(col_w, std::max(frame.action_w0, col_w * 0.6f));
  rctf clear = {x0, x0 + w, std::max(panel.ymin + GEN_DETAIL_FOOT * u, panel.ymin + frame.pad), 0};
  clear.ymax = clear.ymin + h;
  rctf add = clear;
  add.ymin = clear.ymax + frame.action_gap;
  add.ymax = add.ymin + h;
  BLI_snprintf(line, sizeof(line), "Add %d", counts.addable());
  action_button(block,
                add,
                frame,
                counts.addable() ? line : "Nothing to add",
                "mixar.generations_add_selected",
                true,
                counts.addable() > 0,
                "Add the selected images and videos to the moodboard and the 3D assets to "
                "the scene");
  action_button(block,
                clear,
                frame,
                "Clear Selection",
                "mixar.generations_clear_selection",
                false,
                true,
                "Deselect every tile");
}

}  // namespace blender

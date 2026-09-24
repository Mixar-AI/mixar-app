/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Measures the Library pane's labels and resolves `agent_ui_generations_layout.hh`.
 * Geometry decisions live in the header so a host-free test can execute them.
 */

#include "agent_ui_generations_intern.hh"
#include "agent_ui_generations_layout.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_text.hh"

#include "BLI_rect.h"

namespace blender {

rctf gen_rct(const GenBox &box)
{
  rctf rect;
  rect.xmin = box.xmin;
  rect.xmax = box.xmax;
  rect.ymin = box.ymin;
  rect.ymax = box.ymax;
  return rect;
}

GenResolveInput agent_ui_generations_input(const rctf &panel, const float u)
{
  GenResolveInput in{};
  in.panel_xmin = panel.xmin;
  in.panel_xmax = panel.xmax;
  in.panel_ymin = panel.ymin;
  in.panel_ymax = panel.ymax;
  in.u = u;
  in.font_chip = GEN_CHIP_FONT * agent_ui_text_unit();
  in.font_cap = GEN_CAP_FONT * agent_ui_text_unit();
  in.font_title = GEN_TITLE_FONT * agent_ui_text_unit();
  in.font_meta = GEN_META_FONT * agent_ui_text_unit();
  in.font_desc = GEN_DESC_FONT * agent_ui_text_unit();
  in.font_action = GEN_ACTION_FONT * agent_ui_text_unit();
  in.font_lib = GEN_LIB_FONT * agent_ui_text_unit();
  for (int i = 0; i < GEN_LAYOUT_RAIL_COUNT; i++) {
    in.rail_label[i] = pane_text_width(GEN_RAIL_LABELS[i], in.font_chip);
  }
  for (int i = 0; i < GEN_LAYOUT_CHIP_COUNT; i++) {
    in.chip_label[i] = pane_text_width(GEN_FILTER_LABELS[i], in.font_chip);
  }
  for (int i = 0; i < GEN_ACTION_PRIMARY_COUNT; i++) {
    in.action_primary = std::max(in.action_primary,
                                 pane_text_width(GEN_ACTION_PRIMARY[i], in.font_action));
  }
  for (int i = 0; i < GEN_ACTION_SECONDARY_COUNT; i++) {
    in.action_secondary = std::max(in.action_secondary,
                                   pane_text_width(GEN_ACTION_SECONDARY[i], in.font_action));
  }
  in.rail_w_design = GEN_RAIL_W * u;
  in.rail_h_design = GEN_RAIL_H * u;
  in.chip_h_design = 0.0f; /* Height follows the font plus padding, not the 47-unit slab. */
  in.tile_design = GEN_TILE * u;
  in.preview_design = GEN_PREVIEW_W * u;
  in.sort_w_design = GEN_SORT_W * u;
  in.action_h_design = 0.0f;
  in.foot_design = GEN_DETAIL_FOOT * u;
  in.cap_gap_design = GEN_CAP_GAP * u;
  in.row_gap_design = GEN_ROW_GAP * u;
  in.lib_row_design = GEN_LIB_ROW_H * u;
  in.max_cols = GEN_COLS;
  return in;
}

GenFrame agent_ui_generations_frame(const rctf &panel, const float u)
{
  return agent_ui_generations_resolve(agent_ui_generations_input(panel, u));
}

}  // namespace blender

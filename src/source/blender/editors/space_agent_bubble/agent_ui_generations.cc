/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Library — the pane's frame: the source rail, the filter chips and
 * navigation. The tiles and their drag are `agent_ui_generations_grid.cc`,
 * the right-hand inspector is `agent_ui_generations_detail.cc`, and the
 * gathering pass is `agent_ui_generations_data.cc`.
 *
 * Source, filter, sort, browsed library and selection use stock context
 * operators. Native navigation and scrollbars share the grid/rail RNA state.
 */

#include "agent_ui_text.hh"
#include "agent_ui_generations_clip.hh"

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_generations.hh"
#include "agent_ui_generations_intern.hh"
#include "agent_ui_icons.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* -------------------------------------------------------------------- */
/** \name Painters
 * \{ */

void hairline(const float x, const float y0, const float y1, const float u)
{
  pane_column_divider(x, y0, y1, u);
}

/** \} */

}  // namespace

void agent_ui_generations_draw(const bContext *C,
                               ARegion *region,
                               const rctf &panel,
                               const float u)
{
  GenPaneData data;
  agent_ui_generations_gather(C, &data);
  const GenFrame frame = agent_ui_generations_frame(panel, u);

  MIXAR_THEME_LOAD(text, Text);
  MIXAR_THEME_LOAD(strong, TextStrong);
  MIXAR_THEME_LOAD(dim, TextSecondary);
  const float pill_on[4] = GEN_COL_PILL_ON;
  const float pill_off[4] = GEN_COL_PILL_OFF;
  const float chip_off[4] = GEN_COL_CHIP_OFF;

  const float font_chip = frame.font_chip;

  GPU_blend(GPU_BLEND_ALPHA);
  pane_wash_paint(panel, u);

  /* ---- Column dividers ---- */
  const float div_inset = std::max(GEN_DIVIDER_INSET * u, frame.pad * 0.5f);
  const float div_top = panel.ymax - div_inset;
  const float div_bottom = panel.ymin + div_inset;
  hairline(frame.rail_div_x, div_bottom, div_top, u);
  hairline(frame.detail_div_x, div_bottom, div_top, u);

  /* ---- Source rail. Boxes already include padding around the label. ---- */
  struct RailSpec {
    const char *label;
    const char *value;
    GenSource source;
  };
  const RailSpec rail[] = {
      {GEN_RAIL_LABELS[0], "AI", GEN_SOURCE_AI},
      {GEN_RAIL_LABELS[1], "LIBRARY", GEN_SOURCE_LIBRARY},
  };
  rctf rail_rect[2];
  for (int i = 0; i < 2; i++) {
    const bool active = data.source == rail[i].source;
    rctf &r = rail_rect[i];
    r = gen_rct(frame.rail[i]);
    pane_fill_round(&r, std::min(frame.rail_r, BLI_rctf_size_y(&r) * 0.5f), active ? pill_on : pill_off);

    const float cy = BLI_rctf_cent_y(&r);
    if (active) {
      const float dot_r = frame.rail_dot_r;
      rctf dot;
      dot.xmin = frame.rail_dot_x - dot_r;
      dot.xmax = frame.rail_dot_x + dot_r;
      dot.ymin = cy - dot_r;
      dot.ymax = cy + dot_r;
      pane_fill_round(&dot, dot_r, strong);
    }
    char label[64];
    BLI_strncpy(label, rail[i].label, sizeof(label));
    pane_fit_text(label, std::max(1.0f, r.xmax - frame.pad - frame.rail_label_x), font_chip);
    pane_label_left(label, frame.rail_label_x, cy, font_chip, active ? strong : dim);
  }

  /* ---- Filter chips. Same order as GEN_FILTER_LABELS. ---- */
  struct ChipSpec {
    const char *label;
    const char *value;
    GenFilter filter;
  };
  const ChipSpec chips[] = {
      {GEN_FILTER_LABELS[0], "ALL", GEN_FILTER_ALL},
      {GEN_FILTER_LABELS[1], "THREE_D", GEN_FILTER_3D},
      {GEN_FILTER_LABELS[2], "IMAGE", GEN_FILTER_IMAGE},
      {GEN_FILTER_LABELS[3], "VIDEO", GEN_FILTER_VIDEO},
      {GEN_FILTER_LABELS[4], "SPLAT", GEN_FILTER_SPLAT},
  };
  rctf chip_rect[ARRAY_SIZE(chips)];
  for (int i = 0; i < int(ARRAY_SIZE(chips)); i++) {
    const bool active = data.filter == chips[i].filter;
    rctf &r = chip_rect[i];
    r = gen_rct(frame.chip[i]);
    pane_fill_round(&r, std::min(frame.chip_r, BLI_rctf_size_y(&r) * 0.5f), active ? pill_on : chip_off);
    pane_label_centre(chips[i].label,
                      BLI_rctf_cent_x(&r),
                      BLI_rctf_cent_y(&r),
                      font_chip,
                      active ? strong : dim);
  }

  const GenGridMetrics grid = agent_ui_generations_grid_metrics(frame, data);

  /* Sort chip sits on the resolved grid's right edge, not a shrinking tile. */
  rctf sort_rect = gen_rct(frame.sort);
  pane_fill_round(&sort_rect, std::min(frame.chip_r, BLI_rctf_size_y(&sort_rect) * 0.5f), chip_off);
  {
    rctf glyph;
    const float s = std::max(8.0f, BLI_rctf_size_y(&sort_rect) - 2.0f * frame.pad * GEN_PAD_SHRINK);
    glyph.xmin = BLI_rctf_cent_x(&sort_rect) - s * 0.5f;
    glyph.xmax = glyph.xmin + s;
    glyph.ymin = BLI_rctf_cent_y(&sort_rect) - s * 0.5f;
    glyph.ymax = glyph.ymin + s;
    agent_ui_icon_draw(AGENT_ICON_SORT, &glyph, dim, chip_off);
  }

  /* Page chips, only when they fit in the padding between the filters and
   * the sort control — never overlapping a label. */
  rctf page_rect[2]{};
  const bool paged = grid.max_scroll > 0;
  const float page_w = std::max(GEN_PAGE_W * u, frame.chip_h);
  const bool page_fits = paged && frame.sort.xmin - frame.gap - page_w * 2.0f - frame.gap >=
                                      frame.row0_right;
  if (page_fits) {
    page_rect[1].xmax = sort_rect.xmin - frame.gap;
    page_rect[1].xmin = page_rect[1].xmax - page_w;
    page_rect[0].xmax = page_rect[1].xmin - frame.gap;
    page_rect[0].xmin = page_rect[0].xmax - page_w;
    for (int i = 0; i < 2; i++) {
      page_rect[i].ymax = sort_rect.ymax;
      page_rect[i].ymin = sort_rect.ymin;
      const bool enabled = (i == 0) ? (grid.offset > 0) : (grid.offset < grid.max_scroll);
      pane_fill_round(&page_rect[i], std::min(frame.chip_r, BLI_rctf_size_y(&page_rect[i]) * 0.5f), chip_off);
      pane_label_centre((i == 0) ? "\xE2\x80\xB9" : "\xE2\x80\xBA", /* ‹ › */
                        BLI_rctf_cent_x(&page_rect[i]),
                        BLI_rctf_cent_y(&page_rect[i]),
                        font_chip,
                        enabled ? text : dim);
      if (!enabled) {
        page_rect[i] = rctf{};
      }
    }
  }

  /* ---- Controls: one unembossed block over the painted surface. ---- */
  ui::Block *block = ui::block_begin(
      C, region, "agent_island_generations", blender::ui::EmbossType::None);

  auto set_enum = [&](const rctf &r, const char *path, const char *value, const char *tip) {
    ui::Button *but = uiDefButO(block,
                                ui::ButtonType::But,
                                "wm.context_set_enum",
                                blender::wm::OpCallContext::InvokeDefault,
                                "",
                                int(r.xmin),
                                int(r.ymin),
                                short(BLI_rctf_size_x(&r)),
                                short(BLI_rctf_size_y(&r)),
                                tip);
    if (but) {
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path", path);
      RNA_string_set(op_ptr, "value", value);
    }
  };

  for (int i = 0; i < 2; i++) {
    set_enum(rail_rect[i],
             "window_manager.mixar_generations_source",
             rail[i].value,
             (i == 0) ? "Everything Mixar has generated" :
                        "Browse and connect Blender asset libraries");
  }
  agent_ui_generations_libraries(C, block, frame, data);

  for (int i = 0; i < int(ARRAY_SIZE(chips)); i++) {
    set_enum(chip_rect[i],
             "window_manager.mixar_generations_filter",
             chips[i].value,
             "Filter the grid");
  }
  {
    ui::Button *but = uiDefButO(block,
                                ui::ButtonType::But,
                                "wm.context_toggle_enum",
                                blender::wm::OpCallContext::InvokeDefault,
                                "",
                                int(sort_rect.xmin),
                                int(sort_rect.ymin),
                                short(BLI_rctf_size_x(&sort_rect)),
                                short(BLI_rctf_size_y(&sort_rect)),
                                "Newest first / oldest first");
    if (but) {
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path", "window_manager.mixar_generations_sort");
      RNA_string_set(op_ptr, "value_1", "NEWEST");
      RNA_string_set(op_ptr, "value_2", "OLDEST");
    }
  }
  if (paged) {
    if (page_fits) {
      for (int i = 0; i < 2; i++) {
        const rctf &r = page_rect[i];
        if (BLI_rctf_size_x(&r) <= 0) {
          continue;
        }
        ui::Button *but = uiDefButO(block,
                                    ui::ButtonType::But,
                                    "mixar.generations_navigate",
                                    wm::OpCallContext::InvokeDefault,
                                    "",
                                    int(r.xmin),
                                    int(r.ymin),
                                    short(BLI_rctf_size_x(&r)),
                                    short(BLI_rctf_size_y(&r)),
                                    i ? "Next rows" : "Previous rows");
        PointerRNA *op = ui::button_operator_ptr_ensure(but);
        RNA_enum_set(op, "action", 1);
        RNA_float_set(op, "delta", i ? 1 : -1);
      }
    }
    PointerRNA wm = RNA_id_pointer_create(&CTX_wm_manager(C)->id);
    agent_ui_generations_scrollbar(
        block, &wm, "mixar_generations_scroll", grid.scrollbar, BLI_rctf_size_y(&grid.view), grid.max_scroll);
  }

  rctf selected_tile;
  agent_ui_generations_grid(C, block, panel, frame, data, grid, &selected_tile);

  /* The detail column paints AND lays its two actions, so it runs while blend
   * is still on and before the block is closed. */
  agent_ui_generations_detail(C, block, panel, frame, data);

  GPU_blend(GPU_BLEND_NONE);

  ui::block_end(C, block);
  ui::block_draw(C, block);

  /* Clip the selection ring along with partial rows. */
  if (BLI_rctf_size_x(&selected_tile) > 0.0f) {
    const GenViewportClip clip(grid.view);
    MIXAR_THEME_LOAD(accent, AgentAccent);
    const float w = std::max(GEN_SEL_BORDER * u, frame.pad * 0.2f);
    rctf ring = selected_tile;
    BLI_rctf_pad(&ring, -w * 0.5f, -w * 0.5f);
    GPU_blend(GPU_BLEND_ALPHA);
    ui::draw_roundbox_corner_set(ui::CNR_ALL);
    ui::draw_roundbox_4fv_ex(
        &ring, nullptr, nullptr, 1.0f, accent, w, (GEN_TILE_RADIUS * u) - w * 0.5f);
    GPU_blend(GPU_BLEND_NONE);
  }
}

}  // namespace blender

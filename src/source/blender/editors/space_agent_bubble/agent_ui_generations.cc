/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * My Generations — the pane's frame: the source rail, the filter chips and
 * the paging. The tiles and their drag are `agent_ui_generations_grid.cc`,
 * the right-hand inspector is `agent_ui_generations_detail.cc`, and the
 * gathering pass is `agent_ui_generations_data.cc`.
 *
 * \section state Everything is a stock operator
 *
 * Source, filter, sort, page, browsed library and selection are all
 * WindowManager properties, and every control is a plain `wm.context_set_*`
 * button over the painted surface — the pattern the tab strip and the Queue
 * tab already use. The pane owns no operator of its own except the three
 * Python ones that DO something (connect a library, add to scene, add to
 * board).
 */

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"

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

namespace {

/* -------------------------------------------------------------------- */
/** \name Painters
 * \{ */

void hairline(const float x, const float y0, const float y1, const float u)
{
  const float col[4] = GEN_COL_DIVIDER;
  rctf r;
  r.xmin = x;
  r.xmax = x + std::max(1.0f, u);
  r.ymin = y0;
  r.ymax = y1;
  pane_fill_round(&r, 0.0f, col);
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

  const float text[4] = AGENT_COL_TEXT;
  const float strong[4] = AGENT_COL_TEXT_STRONG;
  const float dim[4] = AGENT_COL_TEXT_DIM;
  const float pill_on[4] = GEN_COL_PILL_ON;
  const float pill_off[4] = GEN_COL_PILL_OFF;
  const float chip_off[4] = GEN_COL_CHIP_OFF;

  const float font_chip = GEN_CHIP_FONT * u;

  GPU_blend(GPU_BLEND_ALPHA);
  pane_wash_paint(panel, u);

  /* ---- Column dividers ---- */
  const float div_top = GEN_YTOP(panel, GEN_DIVIDER_INSET, u);
  const float div_bottom = panel.ymin + GEN_DIVIDER_INSET * u;
  hairline(GEN_XL(panel, GEN_DIVIDER_X, u), div_bottom, div_top, u);
  hairline(GEN_XL(panel, GEN_DETAIL_DIVIDER_X, u), div_bottom, div_top, u);

  /* ---- Source rail ---- */
  struct RailSpec {
    const char *label;
    const char *value;
    GenSource source;
  };
  const RailSpec rail[] = {
      {"AI generations", "AI", GEN_SOURCE_AI},
      {"Asset Library", "LIBRARY", GEN_SOURCE_LIBRARY},
  };
  rctf rail_rect[2];
  for (int i = 0; i < 2; i++) {
    const bool active = data.source == rail[i].source;
    rctf &r = rail_rect[i];
    r.xmin = GEN_XL(panel, GEN_PAD, u);
    r.xmax = r.xmin + GEN_RAIL_W * u;
    r.ymax = GEN_YTOP(panel, GEN_RAIL_Y + i * GEN_RAIL_PITCH, u);
    r.ymin = r.ymax - GEN_RAIL_H * u;
    pane_fill_round(&r, GEN_RAIL_RADIUS * u, active ? pill_on : pill_off);

    const float cy = BLI_rctf_cent_y(&r);
    float label_x = r.xmin + GEN_RAIL_LABEL_X * u;
    if (active) {
      const float dot_r = GEN_RAIL_DOT_R * u;
      rctf dot;
      dot.xmin = r.xmin + GEN_RAIL_DOT_X * u - dot_r;
      dot.xmax = dot.xmin + dot_r * 2.0f;
      dot.ymin = cy - dot_r;
      dot.ymax = cy + dot_r;
      pane_fill_round(&dot, dot_r, strong);
    }
    else {
      label_x = r.xmin + GEN_RAIL_LABEL_X * u;
    }
    pane_label_left(rail[i].label, label_x, cy, font_chip, active ? strong : dim);
  }

  /* Registered libraries, listed under the rail while the Asset Library
   * source is active — the design leaves this column empty, and "connect and
   * load all your assets" is exactly what it is for. */
  const int lib_rows = (data.source == GEN_SOURCE_LIBRARY) ? data.lib_count : 0;
  for (int i = 0; i < lib_rows; i++) {
    const bool active = STREQ(data.library, data.lib_names[i]);
    rctf r;
    r.xmin = GEN_XL(panel, GEN_PAD, u);
    r.xmax = r.xmin + GEN_RAIL_W * u;
    r.ymax = GEN_YTOP(panel, GEN_LIB_ROWS_Y + i * GEN_LIB_ROW_PITCH, u);
    r.ymin = r.ymax - GEN_LIB_ROW_H * u;
    if (r.ymin < panel.ymin + GEN_PAD * u) {
      break;
    }
    if (active) {
      pane_fill_round(&r, GEN_META_RADIUS * u, pill_off);
    }
    char name[64];
    BLI_strncpy(name, data.lib_names[i], sizeof(name));
    pane_fit_text(name, BLI_rctf_size_x(&r) - 24.0f * u, GEN_LIB_FONT * u);
    pane_label_left(name,
                    r.xmin + 12.0f * u,
                    BLI_rctf_cent_y(&r),
                    GEN_LIB_FONT * u,
                    active ? text : dim);
  }
  rctf add_lib_rect{};
  if (data.source == GEN_SOURCE_LIBRARY) {
    add_lib_rect.xmin = GEN_XL(panel, GEN_PAD, u);
    add_lib_rect.xmax = add_lib_rect.xmin + GEN_RAIL_W * u;
    add_lib_rect.ymax = GEN_YTOP(panel, GEN_LIB_ROWS_Y + lib_rows * GEN_LIB_ROW_PITCH, u);
    add_lib_rect.ymin = add_lib_rect.ymax - GEN_LIB_ROW_H * u;
    if (add_lib_rect.ymin > panel.ymin + GEN_PAD * u) {
      pane_fill_round(&add_lib_rect, GEN_META_RADIUS * u, pill_off);
      pane_label_left("+  Add Library…",
                      add_lib_rect.xmin + 12.0f * u,
                      BLI_rctf_cent_y(&add_lib_rect),
                      GEN_LIB_FONT * u,
                      text);
    }
    else {
      add_lib_rect = rctf{};
    }
  }

  /* ---- Filter chips ---- */
  struct ChipSpec {
    const char *label;
    const char *value;
    GenFilter filter;
  };
  const ChipSpec chips[] = {
      {"All", "ALL", GEN_FILTER_ALL},
      {"3D", "THREE_D", GEN_FILTER_3D},
      {"Image", "IMAGE", GEN_FILTER_IMAGE},
      {"Video", "VIDEO", GEN_FILTER_VIDEO},
      {"Splats", "SPLAT", GEN_FILTER_SPLAT},
  };
  rctf chip_rect[ARRAY_SIZE(chips)];
  {
    float x = GEN_XL(panel, GEN_GRID_X, u);
    const float y_top = GEN_YTOP(panel, GEN_CHIP_Y, u);
    for (int i = 0; i < int(ARRAY_SIZE(chips)); i++) {
      const bool active = data.filter == chips[i].filter;
      rctf &r = chip_rect[i];
      r.xmin = x;
      r.xmax = x + pane_text_width(chips[i].label, font_chip) + 2.0f * GEN_CHIP_PAD_X * u;
      r.ymax = y_top;
      r.ymin = y_top - GEN_CHIP_H * u;
      pane_fill_round(&r, GEN_CHIP_RADIUS * u, active ? pill_on : chip_off);
      pane_label_centre(chips[i].label,
                        BLI_rctf_cent_x(&r),
                        BLI_rctf_cent_y(&r),
                        font_chip,
                        active ? strong : dim);
      x = r.xmax + GEN_CHIP_GAP * u;
    }
  }

  const GenGridMetrics grid = agent_ui_generations_grid_metrics(panel, u, data);

  /* Sort chip — right-aligned to the DESIGN's grid right edge (its 1127..1183
   * span ends exactly where the fourth column does). Deliberately not the
   * live grid's edge: tiles shrink on a short island, and a chip that slides
   * with them reads as drift in the chip row. */
  rctf sort_rect;
  sort_rect.xmax = GEN_XL(panel, GEN_GRID_RIGHT, u);
  sort_rect.xmin = sort_rect.xmax - GEN_SORT_W * u;
  sort_rect.ymax = GEN_YTOP(panel, GEN_CHIP_Y, u);
  sort_rect.ymin = sort_rect.ymax - GEN_CHIP_H * u;
  pane_fill_round(&sort_rect, GEN_CHIP_RADIUS * u, chip_off);
  {
    rctf glyph;
    const float s = GEN_TAB_GLYPH * u;
    glyph.xmin = BLI_rctf_cent_x(&sort_rect) - s * 0.5f;
    glyph.xmax = glyph.xmin + s;
    glyph.ymin = BLI_rctf_cent_y(&sort_rect) - s * 0.5f;
    glyph.ymax = glyph.ymin + s;
    agent_ui_icon_draw(AGENT_ICON_SORT, &glyph, dim, chip_off);
  }

  /* Page chips, only when there is another page to reach. */
  rctf page_rect[2]{};
  const bool paged = grid.pages > 1;
  if (paged) {
    const float w = GEN_PAGE_W * u;
    const float gap = GEN_PAGE_GAP * u;
    page_rect[1].xmax = sort_rect.xmin - 12.0f * u;
    page_rect[1].xmin = page_rect[1].xmax - w;
    page_rect[0].xmax = page_rect[1].xmin - gap;
    page_rect[0].xmin = page_rect[0].xmax - w;
    for (int i = 0; i < 2; i++) {
      page_rect[i].ymax = sort_rect.ymax;
      page_rect[i].ymin = sort_rect.ymin;
      const bool enabled = (i == 0) ? (grid.page > 0) : (grid.page + 1 < grid.pages);
      pane_fill_round(&page_rect[i], GEN_CHIP_RADIUS * u, chip_off);
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
  uiBlock *block = UI_block_begin(
      C, region, "agent_island_generations", blender::ui::EmbossType::None);

  auto set_enum = [&](const rctf &r, const char *path, const char *value, const char *tip) {
    uiBut *but = uiDefButO(block, ButType::But, "wm.context_set_enum",
                           blender::wm::OpCallContext::InvokeDefault, "",
                           int(r.xmin), int(r.ymin), short(BLI_rctf_size_x(&r)),
                           short(BLI_rctf_size_y(&r)), tip);
    if (but) {
      PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path", path);
      RNA_string_set(op_ptr, "value", value);
    }
  };
  auto set_string = [&](const rctf &r, const char *path, const char *value, const char *tip) {
    uiBut *but = uiDefButO(block, ButType::But, "wm.context_set_string",
                           blender::wm::OpCallContext::InvokeDefault, "",
                           int(r.xmin), int(r.ymin), short(BLI_rctf_size_x(&r)),
                           short(BLI_rctf_size_y(&r)), tip);
    if (but) {
      PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path", path);
      RNA_string_set(op_ptr, "value", value);
    }
    return but;
  };
  auto set_int = [&](const rctf &r, const char *path, const int value, const char *tip) {
    if (BLI_rctf_size_x(&r) <= 0.0f) {
      return;
    }
    uiBut *but = uiDefButO(block, ButType::But, "wm.context_set_int",
                           blender::wm::OpCallContext::InvokeDefault, "",
                           int(r.xmin), int(r.ymin), short(BLI_rctf_size_x(&r)),
                           short(BLI_rctf_size_y(&r)), tip);
    if (but) {
      PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path", path);
      RNA_int_set(op_ptr, "value", value);
    }
  };

  for (int i = 0; i < 2; i++) {
    set_enum(rail_rect[i],
             "window_manager.mixar_generations_source",
             rail[i].value,
             (i == 0) ? "Everything Mixar has generated" :
                        "Browse and connect Blender asset libraries");
  }
  for (int i = 0; i < lib_rows; i++) {
    rctf r;
    r.xmin = GEN_XL(panel, GEN_PAD, u);
    r.xmax = r.xmin + GEN_RAIL_W * u;
    r.ymax = GEN_YTOP(panel, GEN_LIB_ROWS_Y + i * GEN_LIB_ROW_PITCH, u);
    r.ymin = r.ymax - GEN_LIB_ROW_H * u;
    if (r.ymin < panel.ymin + GEN_PAD * u) {
      break;
    }
    /* Clicking the library already shown clears the filter back to all of
     * them, so the row is a toggle rather than a one-way trip. */
    set_string(r,
               "window_manager.mixar_generations_library",
               STREQ(data.library, data.lib_names[i]) ? "" : data.lib_names[i],
               "Show only this asset library");
  }
  if (BLI_rctf_size_x(&add_lib_rect) > 0.0f) {
    uiDefButO(block, ButType::But, "mixar.generations_add_library",
              blender::wm::OpCallContext::InvokeDefault, "",
              int(add_lib_rect.xmin), int(add_lib_rect.ymin),
              short(BLI_rctf_size_x(&add_lib_rect)), short(BLI_rctf_size_y(&add_lib_rect)),
              "Connect a folder as an asset library");
  }

  for (int i = 0; i < int(ARRAY_SIZE(chips)); i++) {
    set_enum(chip_rect[i], "window_manager.mixar_generations_filter", chips[i].value,
             "Filter the grid");
  }
  {
    uiBut *but = uiDefButO(block, ButType::But, "wm.context_toggle_enum",
                           blender::wm::OpCallContext::InvokeDefault, "",
                           int(sort_rect.xmin), int(sort_rect.ymin),
                           short(BLI_rctf_size_x(&sort_rect)),
                           short(BLI_rctf_size_y(&sort_rect)),
                           "Newest first / oldest first");
    if (but) {
      PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path", "window_manager.mixar_generations_sort");
      RNA_string_set(op_ptr, "value_1", "NEWEST");
      RNA_string_set(op_ptr, "value_2", "OLDEST");
    }
  }
  if (paged) {
    set_int(page_rect[0], "window_manager.mixar_generations_page", grid.page - 1,
            "Previous page");
    set_int(page_rect[1], "window_manager.mixar_generations_page", grid.page + 1, "Next page");
  }

  rctf selected_tile;
  agent_ui_generations_grid(C, block, panel, u, data, grid, &selected_tile);

  /* The detail column paints AND lays its two actions, so it runs while blend
   * is still on and before the block is closed. */
  agent_ui_generations_detail(C, block, panel, u, data);

  GPU_blend(GPU_BLEND_NONE);

  UI_block_end(C, block);
  UI_block_draw(C, block);

  /* Selection ring LAST: an asset tile is a preview button, so the block just
   * painted a thumbnail over the whole tile. A ring drawn before that keeps
   * only the half outside the tile edge and reads as a hairline. */
  if (BLI_rctf_size_x(&selected_tile) > 0.0f) {
    const float accent[4] = AGENT_COL_ACCENT;
    const float w = GEN_SEL_BORDER * u;
    rctf ring = selected_tile;
    BLI_rctf_pad(&ring, -w * 0.5f, -w * 0.5f);
    GPU_blend(GPU_BLEND_ALPHA);
    UI_draw_roundbox_corner_set(UI_CNR_ALL);
    UI_draw_roundbox_4fv_ex(
        &ring, nullptr, nullptr, 1.0f, accent, w, (GEN_TILE_RADIUS * u) - w * 0.5f);
    GPU_blend(GPU_BLEND_NONE);
  }
}

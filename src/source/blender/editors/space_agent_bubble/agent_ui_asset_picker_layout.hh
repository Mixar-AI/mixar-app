/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Asset picker layout: the Library pane's frame, re-used.
 *
 * The picker is meant to READ as the Library tab — the same square tile
 * plates with a two-line caption, selection ring, hairline divider and
 * detail column (preview, meta chips, name box, primary + secondary action)
 * — so it has no geometry of its own. It resolves the Library's frame
 * (`agent_ui_generations_resolve`) with its own labels and keeps that
 * frame's padding, gaps, fonts, detail column and action stacking. What
 * differs is only what the Library has and the picker does not need:
 *
 *  - no source rail: the grid starts at the panel's padded left edge, so the
 *    five picks sit on ONE row at the island's default size;
 *  - a header row instead of filter chips: the agent's question (one or two
 *    lines, measured by the painter) and a right-aligned Cancel chip in the
 *    Library's sort-chip slot;
 *  - at most five tiles and no scrolling: the Library's column rule (tiles
 *    never narrower than their caption, capped at the design's 146 units)
 *    with up to five columns, and a tile that shrinks — as the Library's does
 *    for one row — until every row and its caption fit.
 *
 * Blender-free on purpose: `tests/test_agent_asset_picker.py` compiles and
 * executes it across window sizes, UI scales and font sizes.
 */

#pragma once

#include <algorithm>
#include <cmath>

#include "agent_ui_generations_layout.hh"

namespace blender {

/** Mirrors `MIXIE_ASSET_PICKER_MAX` and `asset_picker.MAX_ASSET_PICKS`. */
constexpr int PICK_MAX = 5;

constexpr const char *PICK_ACTION_PRIMARY = "Use This Asset";
constexpr const char *PICK_ACTION_SECONDARY = "Model from Scratch";
constexpr const char *PICK_CANCEL_LABEL = "Cancel";

struct PickResolveInput {
  /** Exactly what the Library frame is resolved from (panel, unit, fonts,
   * design caps); its rail, chip and action label widths are replaced. */
  GenResolveInput base;
  /** Measured widths, in pixels. */
  float cancel_label; /* 0: no Cancel chip. */
  float action_primary;
  float action_secondary;
  /** Lines the question needs at the chip font (1 or 2). */
  int question_lines;
  /** Lines the widest asset NAME needs under its tile at the caption font
   * (1 or 2, measured by the painter against the tile it was given).
   * Library names are "minotaur_sword_001": at the Library's tile width one
   * line ellipsised almost every pick, so the caption grows a line instead. */
  int name_lines;
  /** Picks to lay out (clamped to 1..PICK_MAX). */
  int count;
};

struct PickFrame {
  /** The Library frame the picker shares (pad, gap, fonts, detail column,
   * action widths and stacking). */
  GenFrame gen;
  GenBox question;
  GenBox cancel; /* Zero-size when there is no Cancel answer. */
  int count;
  int cols;
  int rows;
  float tile;
  float caption;
  GenBox tiles[PICK_MAX];
  /** The grid's clip rect: tiles and captions never paint outside it. */
  GenBox view;
};

/** Floor below which a tile stops shrinking; smaller islands clip instead. */
inline float pick_tile_floor(const float u)
{
  return std::max(40.0f * u, 1.0f);
}

inline PickFrame agent_ui_asset_picker_resolve(const PickResolveInput &in)
{
  PickFrame f{};
  GenResolveInput base = in.base;
  /* No rail and no filter chips are drawn: zero widths keep the Library's
   * resolver from reserving more than its floor for them. */
  for (int i = 0; i < GEN_LAYOUT_RAIL_COUNT; i++) {
    base.rail_label[i] = 0.0f;
  }
  base.rail_w_design = 0.0f;
  for (int i = 0; i < GEN_LAYOUT_CHIP_COUNT; i++) {
    base.chip_label[i] = 0.0f;
  }
  base.action_primary = in.action_primary;
  base.action_secondary = in.action_secondary;
  f.gen = agent_ui_generations_resolve(base);
  const GenFrame &g = f.gen;

  f.count = std::clamp(in.count, 1, PICK_MAX);

  /* The grid owns everything left of the detail column's divider. */
  const float grid_x = base.panel_xmin + g.pad;
  const float gutter = std::max(g.pad, 16.0f * g.u);
  const float grid_right = std::max(grid_x + 1.0f, g.detail_div_x - gutter);
  const float grid_w = grid_right - grid_x;

  /* Header row: the question from the grid's left edge, Cancel on its right
   * edge where the Library keeps its sort chip. */
  const float top = base.panel_ymax - std::max(g.pad, 18.0f * g.u);
  const float font = std::max(g.font_chip, 1.0f);
  const int lines = std::clamp(in.question_lines, 1, 2);
  const float text_h = float(lines) * font * 1.35f;
  const float header_h = std::max(g.chip_h, text_h);
  const float chip_pad = g.chip_pad_x > 0.0f ? g.chip_pad_x : g.pad;
  float cancel_w = in.cancel_label > 0.0f ? gen_control_w(in.cancel_label, chip_pad) : 0.0f;
  cancel_w = std::min(cancel_w, grid_w * 0.45f);
  if (cancel_w > 0.0f) {
    const float cy = top - header_h * 0.5f;
    f.cancel = {grid_right - cancel_w, grid_right, cy - g.chip_h * 0.5f, cy + g.chip_h * 0.5f};
  }
  const float question_right = cancel_w > 0.0f ? f.cancel.xmin - g.gap : grid_right;
  f.question = {grid_x, std::max(grid_x + 1.0f, question_right), top - header_h, top};

  /* Grid: the Library's column rule with up to five columns (never more
   * than the picks), then every row made to fit. */
  const float grid_top = top - header_h - g.block_gap;
  const float grid_bottom = std::min(grid_top, base.panel_ymin + g.pad);
  f.view = {grid_x, grid_right, grid_bottom, grid_top};
  const float min_tile = gen_min_tile(std::max(g.font_cap, 1.0f), g.u);
  f.cols = gen_column_count(grid_w, g.tile_gap, min_tile, f.count);
  f.rows = (f.count + f.cols - 1) / f.cols;
  const float tile_cap = std::max(base.tile_design, min_tile);
  const float by_width = gen_tile_size(grid_w, g.tile_gap, f.cols, tile_cap);
  /* Kind + match on the first caption line, the name on one or two more:
   * half a line above the first, 1.35 per further line, half a line under. */
  const int name_lines = std::clamp(in.name_lines, 1, 2);
  f.caption = g.cap_gap + (1.1f + 1.35f * float(name_lines)) * std::max(g.font_cap, 1.0f);
  const float avail = std::max(0.0f, grid_top - grid_bottom);
  const float by_height = (avail - float(f.rows - 1) * g.row_gap) / float(f.rows) - f.caption;
  f.tile = std::max(std::min(by_width, pick_tile_floor(g.u)), std::min(by_width, by_height));

  const float pitch_x = f.tile + g.tile_gap;
  const float pitch_y = f.tile + f.caption + g.row_gap;
  for (int i = 0; i < f.count; i++) {
    const int col = i % f.cols;
    const int row = i / f.cols;
    const float xmin = grid_x + float(col) * pitch_x;
    const float ymax = grid_top - float(row) * pitch_y;
    f.tiles[i] = {xmin, xmin + f.tile, ymax - f.tile, ymax};
  }
  return f;
}

}  // namespace blender

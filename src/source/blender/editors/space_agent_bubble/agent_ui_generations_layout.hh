/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Library pane layout. Every control is the measured label plus padding on
 * all sides. Padding is the larger of an artboard floor and a fraction of
 * the live font, so it survives both a small window and a large UI scale.
 * The grid drops columns before a tile gets narrower than its caption, and
 * action buttons stack before their labels collide.
 *
 * This header is Blender-free on purpose: `tests/test_library_responsive_layout.py`
 * compiles it on its own. `agent_ui_generations_layout.cc` only measures text.
 */

#pragma once

#include <algorithm>
#include <cmath>

namespace blender {

constexpr int GEN_LAYOUT_CHIP_COUNT = 5;
constexpr int GEN_LAYOUT_RAIL_COUNT = 2;

/** Artboard floors (multiplied by the island unit) and em fractions of the
 * font actually being drawn. The larger one is the padding that gets used. */
constexpr float GEN_PAD_FLOOR = 14.0f;
constexpr float GEN_PAD_EM = 0.62f;
constexpr float GEN_GAP_FLOOR = 12.0f;
constexpr float GEN_GAP_EM = 0.50f;
/** Horizontal chip padding may tighten so a row fits, but never below this
 * fraction of the full pad — a label still has air on both sides. */
constexpr float GEN_PAD_SHRINK = 0.72f;

constexpr const char *GEN_RAIL_LABELS[GEN_LAYOUT_RAIL_COUNT] = {"AI generations", "Asset Library"};
constexpr const char *GEN_FILTER_LABELS[GEN_LAYOUT_CHIP_COUNT] = {
    "All", "3D", "Image", "Video", "Splats"};
/** Widest label each action slot can show. The column is stable across
 * selection; `build_actions` must not grow a label past these. */
constexpr const char *GEN_ACTION_PRIMARY[] = {
    "Add to Scene", "Select on Board", "Select in Scene", "Generating…"};
constexpr const char *GEN_ACTION_SECONDARY[] = {"Open Folder", "Already in file", "Open Queue"};
constexpr int GEN_ACTION_PRIMARY_COUNT = 4;
constexpr int GEN_ACTION_SECONDARY_COUNT = 3;

struct GenBox {
  float xmin, xmax, ymin, ymax;
};

struct GenResolveInput {
  float panel_xmin, panel_xmax, panel_ymin, panel_ymax;
  float u;
  float font_chip, font_cap, font_title, font_meta, font_desc, font_action, font_lib;
  float rail_label[GEN_LAYOUT_RAIL_COUNT];
  float chip_label[GEN_LAYOUT_CHIP_COUNT];
  /** Widest primary / secondary action label, in pixels. */
  float action_primary, action_secondary;
  /** Design caps, already in pixels (artboard token × u). 0 disables a cap. */
  float rail_w_design, rail_h_design, chip_h_design, tile_design, preview_design;
  float sort_w_design, action_h_design, foot_design, cap_gap_design, row_gap_design;
  float lib_row_design;
  int max_cols;
};

struct GenFrame {
  float u;
  float pad;
  float gap;
  float font_chip, font_cap, font_title, font_meta, font_desc, font_action, font_lib;

  GenBox rail[GEN_LAYOUT_RAIL_COUNT];
  float rail_label_x;
  float rail_dot_x;
  float rail_dot_r;
  float rail_div_x;
  float rail_r;

  GenBox chip[GEN_LAYOUT_CHIP_COUNT];
  int chip_rows;
  float row0_right;
  float chip_h;
  float chip_r;
  float chip_pad_x;
  GenBox sort;

  float grid_x;
  float grid_right;
  float grid_top;
  float grid_bottom;
  int cols;
  float tile;
  float tile_gap;
  float row_gap;
  float cap_gap;
  float cap_inset;

  float detail_x;
  float detail_w;
  float detail_div_x;
  float foot;
  float block_gap;
  float action_h;
  float action_w0;
  float action_w1;
  float action_gap;
  bool actions_stacked;

  float lib_row_h;
};

inline float gen_pad_px(const float u, const float font)
{
  return std::max(GEN_PAD_FLOOR * u, GEN_PAD_EM * std::max(0.0f, font));
}

inline float gen_gap_px(const float u, const float font)
{
  return std::max(GEN_GAP_FLOOR * u, GEN_GAP_EM * std::max(0.0f, font));
}

inline float gen_control_w(const float text, const float pad)
{
  return std::max(0.0f, text) + 2.0f * std::max(0.0f, pad);
}

inline float gen_control_h(const float font, const float pad)
{
  return std::max(0.0f, font) + 2.0f * std::max(0.0f, pad);
}

/** How many columns fit while every tile stays at least \a min_tile wide. */
inline int gen_column_count(const float grid_w,
                            const float gap,
                            const float min_tile,
                            const int max_cols)
{
  const int cap = std::max(1, max_cols);
  if (!(grid_w > 0.0f)) {
    return 1;
  }
  for (int cols = cap; cols >= 1; cols--) {
    const float tile = (grid_w - float(cols - 1) * std::max(0.0f, gap)) / float(cols);
    if (tile >= min_tile) {
      return cols;
    }
  }
  return 1;
}

inline float gen_tile_size(const float grid_w,
                           const float gap,
                           const int cols,
                           const float max_tile)
{
  const int n = std::max(1, cols);
  const float tile = (grid_w - float(n - 1) * std::max(0.0f, gap)) / float(n);
  const float capped = max_tile > 0.0f ? std::min(tile, max_tile) : tile;
  return std::max(1.0f, capped);
}

inline bool gen_actions_stack(const float content_max,
                              const float primary,
                              const float secondary,
                              const float gap)
{
  return primary + std::max(0.0f, gap) + secondary > content_max;
}

/** A caption-sized tile: a short name, plus padding on both sides. */
inline float gen_min_tile(const float font_cap, const float u)
{
  const float font = std::max(1.0f, font_cap);
  const float pad = gen_pad_px(u, font);
  return std::max(6.5f * font + 2.0f * pad * GEN_PAD_SHRINK, 48.0f * u);
}

inline float gen_row_pad_x(const float available,
                           const float gap,
                           const float *text,
                           const int count,
                           const float pad,
                           const float floor)
{
  if (count <= 0) {
    return pad;
  }
  auto width = [&](const float px) {
    float sum = gap * float(std::max(0, count - 1));
    for (int i = 0; i < count; i++) {
      sum += gen_control_w(text[i], px);
    }
    return sum;
  };
  float px = pad;
  const float stop = std::max(0.0f, floor);
  while (px > stop + 0.05f && width(px) > available) {
    const float next = std::max(stop, px * 0.85f);
    if (next >= px - 0.01f) {
      break;
    }
    px = next;
  }
  return std::max(px, stop);
}

inline GenFrame agent_ui_generations_resolve(const GenResolveInput &in)
{
  GenFrame frame{};
  const float u = std::max(0.0f, in.u);
  frame.u = u;
  const float font = std::max(in.font_chip, 1.0f);
  frame.pad = gen_pad_px(u, font);
  frame.gap = gen_gap_px(u, font);
  frame.font_chip = in.font_chip;
  frame.font_cap = in.font_cap;
  frame.font_title = in.font_title;
  frame.font_meta = in.font_meta;
  frame.font_desc = in.font_desc;
  frame.font_action = in.font_action;
  frame.font_lib = in.font_lib;
  frame.block_gap = std::max(frame.gap, 14.0f * u);

  const float panel_w = std::max(0.0f, in.panel_xmax - in.panel_xmin);
  const float pad = frame.pad;
  const float gap = frame.gap;
  const float font_cap = std::max(in.font_cap, 1.0f);
  const float min_tile = gen_min_tile(font_cap, u);

  const float dot = std::max(8.0f * u, 0.55f * font);
  frame.rail_dot_r = dot * 0.5f;
  const float rail_text = std::max(in.rail_label[0], in.rail_label[1]);
  float rail_w = gen_control_w(rail_text + dot + gap * 0.35f, pad);
  if (in.rail_w_design > 0.0f) {
    rail_w = std::max(rail_w, in.rail_w_design);
  }
  const float rail_cap = std::max(panel_w * 0.32f, rail_text + dot + 2.0f * pad);
  rail_w = std::min(rail_w, std::max(rail_cap, 1.0f));

  frame.rail_r = std::min(std::max(in.rail_h_design, gen_control_h(font, pad)) * 0.5f,
                          std::max(10.0f * u, pad));
  float rail_h = std::max(in.rail_h_design, gen_control_h(font, pad));
  const float panel_h = std::max(0.0f, in.panel_ymax - in.panel_ymin);
  if (panel_h > 0.0f) {
    rail_h = std::min(rail_h, std::max(gen_control_h(font, pad), panel_h * 0.22f));
  }

  const float top = in.panel_ymax - std::max(pad, 18.0f * u);
  frame.rail[0] = {in.panel_xmin + pad, in.panel_xmin + pad + rail_w, top - rail_h, top};
  frame.rail[1] = {
      frame.rail[0].xmin, frame.rail[0].xmax, frame.rail[0].ymin - gap - rail_h, frame.rail[0].ymin - gap};
  frame.rail_label_x = frame.rail[0].xmin + pad + dot + gap * 0.35f;
  frame.rail_dot_x = frame.rail[0].xmin + pad + frame.rail_dot_r;
  frame.rail_div_x = frame.rail[0].xmax + pad;

  const float action_font = std::max(in.font_action, 1.0f);
  const float action_pad = gen_pad_px(u, action_font);
  frame.action_gap = gen_gap_px(u, action_font);
  frame.action_h = std::max(in.action_h_design, gen_control_h(action_font, action_pad));
  const float primary_w = gen_control_w(in.action_primary, action_pad);
  const float secondary_w = gen_control_w(in.action_secondary, action_pad);
  const float each = std::max(primary_w, secondary_w);
  const float pair_w = each * 2.0f + frame.action_gap;

  const float gutter = std::max(pad, 16.0f * u);
  const float grid_reserve = min_tile + pad * 2.0f + gutter;
  float max_detail = panel_w * 0.38f;
  max_detail = std::min(max_detail, std::max(0.0f, panel_w - rail_w - grid_reserve - pad));
  frame.actions_stacked = gen_actions_stack(std::max(max_detail, 1.0f), each, each, frame.action_gap) ||
                          pair_w > panel_w * 0.42f;

  float content_w = frame.actions_stacked ? each : pair_w;
  if (!frame.actions_stacked && in.preview_design > 0.0f) {
    content_w = std::max(content_w, std::min(in.preview_design, std::max(max_detail, pair_w)));
  }
  const float detail_cap = std::max(each, panel_w - rail_w - pad * 3.0f - gutter);
  content_w = std::min(content_w, std::max(detail_cap, each));
  content_w = std::max(1.0f, content_w);
  /* The action keeps the padding around its label. When the rail and the
   * detail column cannot both sit on the panel, the rail gives up width
   * first — its painter fits the label — and only a panel smaller than one
   * padded button clamps the detail. */
  if (content_w + pad * 2.0f + rail_w > panel_w && panel_w > 0.0f) {
    frame.actions_stacked = true;
    content_w = std::max(each, 1.0f);
    float overflow = content_w + pad * 2.0f + rail_w - panel_w;
    const float rail_floor = std::min(rail_w, 2.0f * pad + dot + gap);
    const float shrink = std::min(std::max(0.0f, overflow), std::max(0.0f, rail_w - rail_floor));
    if (shrink > 0.0f) {
      rail_w -= shrink;
      frame.rail[0].xmax = frame.rail[0].xmin + rail_w;
      frame.rail[1].xmax = frame.rail[0].xmax;
      frame.rail_div_x = frame.rail[0].xmax + pad;
      overflow -= shrink;
    }
    if (overflow > 0.5f) {
      content_w = std::max(1.0f, content_w - overflow);
    }
  }
  /* Equal columns only when EACH button still holds its label plus padding. */
  if (!frame.actions_stacked && (content_w - frame.action_gap) * 0.5f < each - 0.5f) {
    frame.actions_stacked = true;
    content_w = std::max(content_w, std::min(each, std::max(1.0f, panel_w - pad * 2.0f)));
  }

  frame.detail_w = content_w;
  frame.detail_x = in.panel_xmax - pad - content_w;
  frame.detail_div_x = frame.detail_x - pad;
  frame.foot = std::max(in.foot_design, pad);
  if (frame.actions_stacked) {
    frame.action_w0 = content_w;
    frame.action_w1 = content_w;
  }
  else {
    const float half = (content_w - frame.action_gap) * 0.5f;
    frame.action_w0 = half;
    frame.action_w1 = half;
  }

  frame.grid_x = frame.rail_div_x + pad;
  frame.grid_right = frame.detail_div_x - gutter;
  if (frame.grid_right < frame.grid_x + 1.0f) {
    frame.grid_right = frame.grid_x + 1.0f;
  }
  const float grid_w = frame.grid_right - frame.grid_x;
  frame.tile_gap = gap;
  frame.cols = gen_column_count(grid_w, frame.tile_gap, min_tile, std::max(1, in.max_cols));
  /* Don't cap a tile below the caption minimum when the column is wider —
   * that is how a small window was ellipsizing every name. */
  const float tile_cap = std::max(in.tile_design, min_tile);
  frame.tile = gen_tile_size(grid_w, frame.tile_gap, frame.cols, tile_cap);

  frame.chip_h = std::max(in.chip_h_design, gen_control_h(font, pad));
  frame.chip_r = std::min(frame.chip_h * 0.5f, std::max(10.0f * u, pad * 0.7f));
  const float sort_w = std::max(in.sort_w_design, frame.chip_h);
  frame.sort = {frame.grid_right - sort_w, frame.grid_right, top - frame.chip_h, top};

  const float pad_floor = std::max(pad * GEN_PAD_SHRINK, GEN_PAD_EM * GEN_PAD_SHRINK * font);
  const float row0 = frame.sort.xmin - gap - frame.grid_x;
  frame.chip_pad_x = gen_row_pad_x(
      row0, gap, in.chip_label, GEN_LAYOUT_CHIP_COUNT, pad, pad_floor);

  float x = frame.grid_x;
  float y_top = top;
  float limit = frame.sort.xmin - gap;
  int row = 0;
  frame.row0_right = frame.grid_x;
  for (int i = 0; i < GEN_LAYOUT_CHIP_COUNT; i++) {
    const float w = gen_control_w(in.chip_label[i], frame.chip_pad_x);
    const bool overflow = w > std::max(0.0f, limit - frame.grid_x) ||
                          (x > frame.grid_x && x + w > limit);
    if (overflow) {
      row++;
      x = frame.grid_x;
      y_top -= frame.chip_h + gap;
      limit = frame.grid_right;
    }
    frame.chip[i] = {x, x + w, y_top - frame.chip_h, y_top};
    if (row == 0) {
      frame.row0_right = frame.chip[i].xmax;
    }
    x += w + gap;
  }
  frame.chip_rows = row + 1;

  float lowest = frame.chip[0].ymin;
  for (int i = 1; i < GEN_LAYOUT_CHIP_COUNT; i++) {
    lowest = std::min(lowest, frame.chip[i].ymin);
  }
  frame.grid_top = lowest - frame.block_gap;
  frame.grid_bottom = in.panel_ymin + pad;
  frame.cap_gap = std::max(in.cap_gap_design, 0.45f * font_cap);
  frame.row_gap = std::max(in.row_gap_design, gap);
  frame.cap_inset = std::min(pad * 0.5f, std::max(4.0f * u, 0.35f * font_cap));
  frame.lib_row_h = std::max(in.lib_row_design, gen_control_h(std::max(in.font_lib, 1.0f), pad));
  return frame;
}

}  // namespace blender

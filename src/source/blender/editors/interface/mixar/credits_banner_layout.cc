/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include <algorithm>

#include "BLI_rect.h"
#include "UI_interface.hh"
#include "UI_mixar_motion.hh"
#include "WM_api.hh"

#include "credits_banner.hh"

namespace blender::ui::credits_banner {

float appear_factor(const State &state, const double now)
{
  if (mixar_motion_reduced()) {
    return state.closing_at > 0.0 ? 0.0f : 1.0f;
  }
  float t = float(std::clamp((now - state.opened_at) / ENTER_SECONDS, 0.0, 1.0));
  t = 1.0f - (1.0f - t) * (1.0f - t) * (1.0f - t);
  if (state.closing_at > 0.0) {
    t *= 1.0f - float(std::clamp((now - state.closing_at) / EXIT_SECONDS, 0.0, 1.0));
  }
  return t;
}

Layout layout_compute(const State &state, const float appear)
{
  Layout l{};
  const float winx = float(WM_window_native_pixel_x(state.win));
  const float winy = float(WM_window_native_pixel_y(state.win));
  const float w = std::min({640.0f * UI_SCALE_FAC, winx * 0.88f, winy * 0.88f / 0.72f});
  const float cw = w * (0.97f + 0.03f * appear);
  const float ch = cw * 0.72f;
  const float cx = winx * 0.5f;
  const float cy = winy * 0.5f;
  BLI_rctf_init(&l.card, cx - cw * 0.5f, cx + cw * 0.5f, cy - ch * 0.5f, cy + ch * 0.5f);
  l.radius = cw * 0.042f;
  l.button_h = ch * 0.11f;
  const float x0 = l.card.xmin + cw * 0.04f;
  const float y0 = l.card.ymin + ch * 0.06f;
  const float gap = cw * 0.03f;
  const float bw = cw * 0.25f;
  for (int t = TARGET_UPGRADE; t <= TARGET_REFER; t++) {
    const float x = x0 + float(t) * (bw + gap);
    BLI_rctf_init(&l.targets[t], x, x + bw, y0, y0 + l.button_h);
  }
  BLI_rctf_init(&l.targets[TARGET_CREATOR], x0 + 2.0f * (bw + gap),
                l.card.xmax - cw * 0.04f, y0, y0 + l.button_h);
  BLI_rctf_init(&l.art, cx - cw * 0.22f, cx + cw * 0.22f,
                y0 + l.button_h, l.card.ymax - ch * 0.31f);
  const float close = cw * 0.057f;
  const float inset = cw * 0.066f;
  BLI_rctf_init(&l.targets[TARGET_CLOSE], l.card.xmax - inset - close,
                l.card.xmax - inset, l.card.ymax - ch * 0.18f,
                l.card.ymax - ch * 0.18f + close);
  return l;
}

rctf slider_thumb(const Layout &layout, const float progress)
{
  const rctf &track = layout.targets[TARGET_CREATOR];
  const float pad = layout.button_h * 0.075f;
  const float size = layout.button_h - pad * 2.0f;
  const float travel = BLI_rctf_size_x(&track) - 2.0f * pad - size;
  const float x = track.xmin + pad + travel * std::clamp(progress, 0.0f, 1.0f);
  rctf thumb;
  BLI_rctf_init(&thumb, x, x + size, track.ymin + pad, track.ymax - pad);
  return thumb;
}

float slider_progress(const Layout &layout, const float center_x)
{
  const rctf start = slider_thumb(layout, 0.0f);
  const rctf end = slider_thumb(layout, 1.0f);
  const float travel = BLI_rctf_cent_x(&end) - BLI_rctf_cent_x(&start);
  return std::clamp((center_x - BLI_rctf_cent_x(&start)) / std::max(travel, 1.0f), 0.0f, 1.0f);
}

const char *creator_hint(const State &state)
{
  if (state.slide >= SLIDE_COMPLETE) {
    return state.dragging ? "Release to continue" : "Enter to continue";
  }
  if (state.focus == TARGET_CREATOR) {
    return "Press right to slide";
  }
  return state.hover == TARGET_CREATOR || state.dragging ? "Slide to continue" : "Creator Program";
}

Target hit_test(const Layout &layout, const float x, const float y)
{
  for (int t = 0; t < TARGET_COUNT; t++) {
    if (BLI_rctf_isect_pt(&layout.targets[t], x, y)) {
      return Target(t);
    }
  }
  return TARGET_NONE;
}

}  // namespace blender::ui::credits_banner

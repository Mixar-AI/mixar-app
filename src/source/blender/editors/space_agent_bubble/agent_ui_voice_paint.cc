/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Voice control artwork: stop square, live ECG trace, and the Voice chip's
 * contents for each fitted form. See agent_ui_voice_paint.hh.
 */

#include <algorithm>
#include <string>

#include "BLI_rect.h"
#include "BLI_time.h"

#include "DNA_screen_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_mixar.hh"
#include "UI_mixar_motion.hh"

#include "agent_ui_icons.hh"
#include "agent_ui_voice_motion.hh"
#include "agent_ui_voice_paint.hh"

namespace blender {

void agent_ui_draw_stop_glyph(const rctf &box, const float color[4])
{
  const float s = std::min(BLI_rctf_size_x(&box), BLI_rctf_size_y(&box)) * 0.58f;
  const float cx = BLI_rctf_cent_x(&box);
  const float cy = BLI_rctf_cent_y(&box);
  const rctf square{cx - s * 0.5f, cx + s * 0.5f, cy - s * 0.5f, cy + s * 0.5f};
  ui::mixar_fill_round(square, s * 0.2f, color);
}

void agent_ui_draw_voice_wave(const rctf &box, const double now, const float level, const float color[4])
{
  const float w = BLI_rctf_size_x(&box);
  const float h = BLI_rctf_size_y(&box);
  if (w <= 1.0f || h <= 1.0f) {
    return;
  }
  float points[AGENT_VOICE_WAVE_MAX_POINTS][2];
  const int count = agent_voice_wave_points(now, level, ui::mixar_motion_reduced(), points);
  if (count < 2) {
    return;
  }
  /* Anti-aliased at the real width: GPU_line_width draws one hairline pixel on
   * Metal (see mixie_chat_ink_overlay.cc). */
  const float line_w = std::max(1.0f, h * 0.11f);
  const float cy = BLI_rctf_cent_y(&box);
  const float half = h * 0.5f - line_w;

  float viewport[4];
  GPU_viewport_size_get_f(viewport);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_POLYLINE_UNIFORM_COLOR);
  immUniform2fv("viewportSize", &viewport[2]);
  immUniform1f("lineWidth", line_w);
  immUniform1i("lineSmooth", 1);
  immUniformColor4fv(color);
  immBegin(GPU_PRIM_LINE_STRIP, count);
  for (int i = 0; i < count; i++) {
    immVertex2f(pos, box.xmin + points[i][0] * w, cy + points[i][1] * half);
  }
  immEnd();
  immUnbindProgram();

  /* The write head: new beats enter here. */
  const float head_x = box.xmin + points[count - 1][0] * w;
  const float head_y = cy + points[count - 1][1] * half;
  const float r = line_w * 0.95f;
  ui::mixar_fill_round(rctf{head_x - r, head_x + r, head_y - r, head_y + r}, r, color);
}

void agent_ui_draw_voice_chip(ARegion *region,
                              const rctf &chip,
                              const int form,
                              const bool capturing,
                              const char *label,
                              const float level,
                              const float text_size,
                              const float icon_edge,
                              const float icon_gap,
                              const float wave_w,
                              const float color[4],
                              const float fill[4])
{
  const float cy = BLI_rctf_cent_y(&chip);
  const bool show_label = capturing ? form <= 1 : form == 0;
  const bool show_wave = capturing && form == 0;
  const char *word = capturing ? "Stop" : (label && label[0] ? label : "Voice");

  float wave_room = show_wave ? wave_w + icon_gap : 0.0f;
  std::string text;
  if (show_label) {
    const float room = BLI_rctf_size_x(&chip) - icon_edge - wave_room - icon_gap * 3.0f;
    text = ui::mixar_fit_text(word, std::max(0.0f, room), text_size);
  }
  const float label_w = text.empty() ? 0.0f : icon_gap + ui::mixar_text_width(text.c_str(), text_size);
  float x = BLI_rctf_cent_x(&chip) - (icon_edge + label_w + wave_room) * 0.5f;

  const rctf icon{x, x + icon_edge, cy - icon_edge * 0.5f, cy + icon_edge * 0.5f};
  if (capturing) {
    agent_ui_draw_stop_glyph(icon, color);
  }
  else {
    agent_ui_icon_draw(AGENT_ICON_MIC, &icon, color, fill);
  }
  x += icon_edge;
  if (!text.empty()) {
    ui::mixar_label_left(text.c_str(), x + icon_gap, cy, text_size, color);
    x += label_w;
  }
  if (!show_wave) {
    return;
  }
  x += icon_gap;
  const double now = BLI_time_now_seconds();
  const rctf wave{x, x + wave_w, cy - icon_edge * 0.5f, cy + icon_edge * 0.5f};
  agent_ui_draw_voice_wave(wave, now, level, color);

  /* Keep only the region that shows the chip repainting (the island paints in
   * three clipped regions; the chip row is the composer's). */
  if (region && !ui::mixar_motion_reduced() && chip.ymax > float(region->winrct.ymin) &&
      chip.ymin < float(region->winrct.ymax))
  {
    ui::mixar_motion_request(region, now + AGENT_VOICE_WAVE_FRAME_SECONDS);
  }
}

}  // namespace blender

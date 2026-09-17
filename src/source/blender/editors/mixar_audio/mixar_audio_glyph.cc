/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edmixaraudio
 *
 * The mic button and its waveform, painted from primitives.
 *
 * See `ED_mixar_audio_ui.hh` for why this is hand-drawn rather than an
 * `ICON_*`. Everything is built from two shapes — a filled rounded box and a
 * thick arc — so the glyph keeps its weight at any size and in either theme,
 * and so the moodboard canvas can draw it under a zoom matrix without the
 * hinting artifacts a blitted icon would pick up.
 *
 * Colour literals are float[4] with alpha stated explicitly. That is not
 * decoration: a three-value initializer zero-fills alpha, and a shape drawn
 * with alpha 0 is INVISIBLE with no other symptom — the exact way the account
 * card's quota bar once disappeared.
 */

#include <algorithm>
#include <cmath>

#include "BLI_rect.h"
#include "BLI_sys_types.h" /* uint */

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "ED_mixar_audio_ui.hh"

namespace {

constexpr float PI_F = 3.14159265358979f;
constexpr int ARC_SEGMENTS = 24;

/* Palette. Kept local because these are the voice feature's own accents and
 * nothing else consumes them; they are deliberately theme-independent for the
 * same reason the moodboard canvas is — a recording indicator that reads as
 * "live" in one theme and as "disabled" in another is worse than a constant. */
const float COLOR_PLATE_IDLE[4] = {1.0f, 1.0f, 1.0f, 0.06f};
const float COLOR_PLATE_HOVER[4] = {1.0f, 1.0f, 1.0f, 0.12f};
const float COLOR_GLYPH_IDLE[4] = {0.78f, 0.80f, 0.84f, 1.0f};
const float COLOR_GLYPH_ACTIVE[4] = {1.0f, 1.0f, 1.0f, 1.0f};
const float COLOR_RECORD[4] = {0.94f, 0.29f, 0.31f, 1.0f};
const float COLOR_RECORD_PLATE[4] = {0.94f, 0.29f, 0.31f, 0.20f};
const float COLOR_BUSY[4] = {0.36f, 0.78f, 0.90f, 1.0f};
const float COLOR_WAVE[4] = {0.94f, 0.42f, 0.44f, 1.0f};
const float COLOR_WAVE_REST[4] = {1.0f, 1.0f, 1.0f, 0.14f};

struct ImmContext {
  uint pos;
};

ImmContext begin_solid(const float color[4])
{
  GPUVertFormat *format = immVertexFormat();
  ImmContext ctx;
  ctx.pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
  return ctx;
}

/* A filled rounded box. `radius` is clamped to half the smaller side, so
 * passing a large radius gives a capsule — which is exactly how the mic body
 * and the record pill are drawn. */
void fill_round_box(const rctf *rect, float radius, const float color[4])
{
  const float w = BLI_rctf_size_x(rect);
  const float h = BLI_rctf_size_y(rect);
  if (w <= 0.0f || h <= 0.0f) {
    return;
  }
  const float r = std::min(radius, std::min(w, h) * 0.5f);
  const ImmContext ctx = begin_solid(color);

  immRectf(ctx.pos, rect->xmin + r, rect->ymin, rect->xmax - r, rect->ymax);
  immRectf(ctx.pos, rect->xmin, rect->ymin + r, rect->xmin + r, rect->ymax - r);
  immRectf(ctx.pos, rect->xmax - r, rect->ymin + r, rect->xmax, rect->ymax - r);

  const float corners[4][3] = {
      {rect->xmin + r, rect->ymin + r, PI_F},
      {rect->xmax - r, rect->ymin + r, 1.5f * PI_F},
      {rect->xmax - r, rect->ymax - r, 0.0f},
      {rect->xmin + r, rect->ymax - r, 0.5f * PI_F},
  };
  for (const auto &corner : corners) {
    immBegin(GPU_PRIM_TRI_FAN, ARC_SEGMENTS / 2 + 2);
    immVertex2f(ctx.pos, corner[0], corner[1]);
    for (int i = 0; i <= ARC_SEGMENTS / 2; i++) {
      const float angle = corner[2] + (PI_F * 0.5f) * float(i) / float(ARC_SEGMENTS / 2);
      immVertex2f(ctx.pos, corner[0] + r * cosf(angle), corner[1] + r * sinf(angle));
    }
    immEnd();
  }
  immUnbindProgram();
}

void fill_disc(float cx, float cy, float radius, const float color[4])
{
  if (radius <= 0.0f) {
    return;
  }
  const ImmContext ctx = begin_solid(color);
  immBegin(GPU_PRIM_TRI_FAN, ARC_SEGMENTS + 2);
  immVertex2f(ctx.pos, cx, cy);
  for (int i = 0; i <= ARC_SEGMENTS; i++) {
    const float angle = 2.0f * PI_F * float(i) / float(ARC_SEGMENTS);
    immVertex2f(ctx.pos, cx + radius * cosf(angle), cy + radius * sinf(angle));
  }
  immEnd();
  immUnbindProgram();
}

/* A thick arc, built as a triangle strip between an inner and an outer radius.
 * Line primitives were the obvious alternative and are the wrong tool: the
 * line width a driver honours varies, and the moodboard draws this under a
 * zoom matrix where a 2px line stays 2px while everything around it grows. */
void fill_arc(float cx,
              float cy,
              float radius,
              float thickness,
              float start_angle,
              float sweep,
              const float color[4])
{
  if (radius <= 0.0f || thickness <= 0.0f || sweep == 0.0f) {
    return;
  }
  const float inner = std::max(0.0f, radius - thickness * 0.5f);
  const float outer = radius + thickness * 0.5f;
  const ImmContext ctx = begin_solid(color);
  immBegin(GPU_PRIM_TRI_STRIP, (ARC_SEGMENTS + 1) * 2);
  for (int i = 0; i <= ARC_SEGMENTS; i++) {
    const float angle = start_angle + sweep * float(i) / float(ARC_SEGMENTS);
    const float c = cosf(angle);
    const float s = sinf(angle);
    immVertex2f(ctx.pos, cx + inner * c, cy + inner * s);
    immVertex2f(ctx.pos, cx + outer * c, cy + outer * s);
  }
  immEnd();
  immUnbindProgram();
}

/* The mic itself: a capsule body, the cradle arc under it, and a short stem.
 * Proportions are fractions of the button, so it scales as one piece. */
void draw_mic_glyph(const rctf *rect, const float color[4])
{
  const float w = BLI_rctf_size_x(rect);
  const float h = BLI_rctf_size_y(rect);
  const float size = std::min(w, h);
  const float cx = (rect->xmin + rect->xmax) * 0.5f;
  const float cy = (rect->ymin + rect->ymax) * 0.5f;

  const float body_w = size * 0.26f;
  const float body_h = size * 0.42f;
  const float body_bottom = cy - size * 0.06f;

  rctf body;
  body.xmin = cx - body_w * 0.5f;
  body.xmax = cx + body_w * 0.5f;
  body.ymin = body_bottom;
  body.ymax = body_bottom + body_h;
  fill_round_box(&body, body_w * 0.5f, color);

  /* The cradle is the lower half of a ring — a half-circle opening upward,
   * which is what makes the shape read as a microphone rather than a pill. */
  const float cradle_radius = size * 0.27f;
  fill_arc(cx,
           body_bottom + size * 0.04f,
           cradle_radius,
           std::max(1.0f, size * 0.075f),
           PI_F,
           PI_F,
           color);

  /* Stem down to the base. */
  rctf stem;
  stem.xmin = cx - size * 0.035f;
  stem.xmax = cx + size * 0.035f;
  stem.ymin = body_bottom - cradle_radius - size * 0.10f;
  stem.ymax = body_bottom - cradle_radius + size * 0.02f;
  fill_round_box(&stem, size * 0.035f, color);
}

/* The stop glyph: a rounded square. Deliberately NOT a second mic in another
 * colour — the button is a toggle, and the only unambiguous way to say "press
 * again to end this" is the shape every recorder uses. */
void draw_stop_glyph(const rctf *rect, const float color[4])
{
  const float size = std::min(BLI_rctf_size_x(rect), BLI_rctf_size_y(rect));
  const float cx = (rect->xmin + rect->xmax) * 0.5f;
  const float cy = (rect->ymin + rect->ymax) * 0.5f;
  const float half = size * 0.17f;

  rctf square;
  square.xmin = cx - half;
  square.xmax = cx + half;
  square.ymin = cy - half;
  square.ymax = cy + half;
  fill_round_box(&square, half * 0.35f, color);
}

}  // namespace

void ED_mixar_voice_draw_button(const rctf *rect,
                                MixarVoiceVisual state,
                                float level,
                                float pulse,
                                bool hovered)
{
  if (rect == nullptr) {
    return;
  }
  const float size = std::min(BLI_rctf_size_x(rect), BLI_rctf_size_y(rect));
  if (size <= 0.0f) {
    return;
  }
  const float cx = (rect->xmin + rect->xmax) * 0.5f;
  const float cy = (rect->ymin + rect->ymax) * 0.5f;

  GPU_blend(GPU_BLEND_ALPHA);

  switch (state) {
    case MixarVoiceVisual::Recording: {
      /* The halo is the voice made visible: its radius follows the live level
       * over a floor, so a quiet moment still shows a ring (the recording is
       * running) and a loud one blooms. The slow breathe underneath keeps it
       * alive while someone pauses mid-sentence. */
      const float breathe = 0.5f + 0.5f * sinf(pulse * 2.2f);
      const float reach = std::clamp(level, 0.0f, 1.0f);
      const float halo_radius = size * (0.42f + 0.30f * reach + 0.05f * breathe);
      float halo_color[4] = {
          COLOR_RECORD[0], COLOR_RECORD[1], COLOR_RECORD[2], 0.16f + 0.22f * reach};
      fill_disc(cx, cy, halo_radius, halo_color);

      rctf plate = *rect;
      fill_round_box(&plate, size * 0.30f, COLOR_RECORD_PLATE);
      draw_stop_glyph(rect, COLOR_RECORD);
      break;
    }

    case MixarVoiceVisual::Transcribing: {
      rctf plate = *rect;
      fill_round_box(&plate, size * 0.30f, hovered ? COLOR_PLATE_HOVER : COLOR_PLATE_IDLE);
      /* A three-quarter arc spun by the clock. The mic stays faintly behind
       * it so the button keeps its identity while it works. */
      float ghost[4] = {
          COLOR_GLYPH_IDLE[0], COLOR_GLYPH_IDLE[1], COLOR_GLYPH_IDLE[2], 0.25f};
      draw_mic_glyph(rect, ghost);
      fill_arc(cx,
               cy,
               size * 0.34f,
               std::max(1.5f, size * 0.075f),
               pulse * 4.0f,
               PI_F * 1.4f,
               COLOR_BUSY);
      break;
    }

    case MixarVoiceVisual::Error: {
      rctf plate = *rect;
      float plate_color[4] = {
          COLOR_RECORD[0], COLOR_RECORD[1], COLOR_RECORD[2], 0.14f};
      fill_round_box(&plate, size * 0.30f, plate_color);
      draw_mic_glyph(rect, COLOR_RECORD);
      break;
    }

    case MixarVoiceVisual::Idle:
    default: {
      rctf plate = *rect;
      fill_round_box(&plate, size * 0.30f, hovered ? COLOR_PLATE_HOVER : COLOR_PLATE_IDLE);
      draw_mic_glyph(rect, hovered ? COLOR_GLYPH_ACTIVE : COLOR_GLYPH_IDLE);
      break;
    }
  }

  GPU_blend(GPU_BLEND_NONE);
}

void ED_mixar_voice_draw_waveform(const rctf *rect, const float *levels, int count)
{
  if (rect == nullptr) {
    return;
  }
  const float width = BLI_rctf_size_x(rect);
  const float height = BLI_rctf_size_y(rect);
  if (width <= 0.0f || height <= 0.0f) {
    return;
  }
  const float mid_y = (rect->ymin + rect->ymax) * 0.5f;

  GPU_blend(GPU_BLEND_ALPHA);

  if (levels == nullptr || count <= 0) {
    /* The resting line. An empty strip where a waveform belongs reads as a
     * broken meter; a flat line reads as silence, which is the truth. */
    rctf line;
    line.xmin = rect->xmin;
    line.xmax = rect->xmax;
    line.ymin = mid_y - std::max(0.5f, height * 0.015f);
    line.ymax = mid_y + std::max(0.5f, height * 0.015f);
    fill_round_box(&line, height * 0.015f, COLOR_WAVE_REST);
    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  const float slot = width / float(count);
  const float bar_w = std::max(1.0f, slot * 0.55f);
  for (int i = 0; i < count; i++) {
    const float level = std::clamp(levels[i], 0.0f, 1.0f);
    /* A floor so even silence draws a dot: a gap in the middle of a waveform
     * looks like dropped audio, and silence between words is not that. */
    const float bar_h = std::max(height * 0.06f, level * height * 0.9f);
    const float x = rect->xmin + slot * (float(i) + 0.5f);

    rctf bar;
    bar.xmin = x - bar_w * 0.5f;
    bar.xmax = x + bar_w * 0.5f;
    bar.ymin = mid_y - bar_h * 0.5f;
    bar.ymax = mid_y + bar_h * 0.5f;

    /* Older samples fade, so the strip reads as time flowing rightward. */
    const float age = float(i + 1) / float(count);
    float color[4] = {COLOR_WAVE[0], COLOR_WAVE[1], COLOR_WAVE[2], 0.35f + 0.65f * age};
    fill_round_box(&bar, bar_w * 0.5f, color);
  }

  GPU_blend(GPU_BLEND_NONE);
}

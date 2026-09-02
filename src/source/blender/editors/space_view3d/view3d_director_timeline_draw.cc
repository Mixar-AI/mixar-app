/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Flow-style ruler, camera strip, beat handles, and playhead drawing.
 */

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_string.h"

#include "DNA_screen_types.h"

#include "GPU_immediate.hh"
#include "GPU_immediate_util.hh"
#include "GPU_shader_shared_utils.hh"
#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_interface_icons.hh"
#include "UI_resources.hh"

#include "view3d_director_timeline.hh"

namespace {

/* Design tokens: a hairline major tick, dimmer minor dots, quiet labels. */
constexpr float RULER_COLOR[4] = {0.435f, 0.435f, 0.435f, 1.0f};  /* #6F6F6F */
constexpr float RULER_MINOR_COLOR[4] = {0.278f, 0.278f, 0.278f, 1.0f}; /* #474747 */
constexpr float TIME_COLOR[4] = {0.604f, 0.604f, 0.604f, 1.0f};   /* #9A9A9A */
constexpr float STRIP_COLOR[4] = {1.0f, 0.72f, 0.48f, 1.0f};
constexpr float STRIP_HOVER_COLOR[4] = {1.0f, 0.76f, 0.54f, 1.0f};
constexpr float HANDLE_COLOR[4] = {1.0f, 0.83f, 0.69f, 1.0f};
constexpr float HANDLE_ACTIVE_COLOR[4] = {1.0f, 0.90f, 0.80f, 1.0f};
constexpr float STRIP_TEXT_COLOR[4] = {1.0f, 0.98f, 0.96f, 1.0f};
constexpr float PLAYHEAD_COLOR[4] = {0.851f, 0.851f, 0.851f, 1.0f}; /* #D9D9D9 */
constexpr float PLAYHEAD_TEXT_COLOR[4] = {0.035f, 0.045f, 0.055f, 1.0f};

void draw_rect(
    const float x1, const float y1, const float x2, const float y2, const float color[4])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
  immRectf(pos, x1, y1, x2, y2);
  immUnbindProgram();
}

void draw_round_rect(const rctf &rect, const float radius, const float color[4])
{
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(&rect, true, radius, color);
}

void draw_text(
    const char *text, const float x, const float y, const float size, const float color[4])
{
  const int font = BLF_default();
  BLF_size(font, size);
  BLF_color4fv(font, color);
  BLF_position(font, x, y, 0.0f);
  BLF_draw(font, text, strlen(text));
  GPU_blend(GPU_BLEND_ALPHA);
}

float text_width(const char *text, const float size)
{
  const int font = BLF_default();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

void draw_camera_icon(const float x, const float y, const float size)
{
  const uchar color[4] = {255, 250, 245, 255};
  UI_icon_draw_ex(
      x, y, ICON_CAMERA_DATA, 16.0f / size, 1.0f, 0.0f, color, false, UI_NO_ICON_OVERLAY_TEXT);
  GPU_blend(GPU_BLEND_ALPHA);
}

void reset_view(const DirectorViewState &state, DirectorTimelineRuntime *runtime)
{
  const float fps = std::max(state.fps, 0.001f);
  const int first = state.beats.is_empty() ? state.scene_frame_start : state.frame_start;
  const int last = state.beats.is_empty() ? state.scene_frame_start : state.frame_end;
  runtime->view_start_frame = float(std::min(state.scene_frame_start, first));
  runtime->view_span_frames = std::max(fps * 5.0f, float(last) + fps - runtime->view_start_frame);
  runtime->view_initialized = true;
  runtime->view_user_modified = false;
}

void sync_view(const DirectorViewState &state, DirectorTimelineRuntime *runtime)
{
  const int first = state.beats.is_empty() ? state.scene_frame_start : state.frame_start;
  const int last = state.beats.is_empty() ? state.scene_frame_start : state.frame_end;
  const int count = int(state.beats.size());
  const bool shot_changed = runtime->shot_identity != state.shot_identity;
  const bool content_changed = runtime->content_first != first || runtime->content_last != last ||
                               runtime->content_count != count;
  if (!runtime->view_initialized || shot_changed ||
      (content_changed && !runtime->view_user_modified))
  {
    reset_view(state, runtime);
  }
  runtime->shot_identity = state.shot_identity;
  runtime->content_first = first;
  runtime->content_last = last;
  runtime->content_count = count;
}

float major_tick_seconds(const float pixels_per_second)
{
  constexpr std::array<float, 15> steps = {0.1f,
                                           0.2f,
                                           0.5f,
                                           1.0f,
                                           2.0f,
                                           5.0f,
                                           10.0f,
                                           15.0f,
                                           30.0f,
                                           60.0f,
                                           120.0f,
                                           300.0f,
                                           600.0f,
                                           1800.0f,
                                           3600.0f};
  for (const float step : steps) {
    if (step * pixels_per_second >= 86.0f * UI_SCALE_FAC) {
      return step;
    }
  }
  return steps.back();
}

/** Ruler label for \a seconds, in the unit the Duration chips select. */
void ruler_label(const DirectorViewState &state,
                 const float seconds,
                 const float major_seconds,
                 char *out,
                 const int size)
{
  if (state.ruler_minutes) {
    const int total = int(std::round(seconds));
    BLI_snprintf(out, size, "%d:%02d", total / 60, std::abs(total % 60));
    return;
  }
  if (major_seconds < 1.0f) {
    BLI_snprintf(out, size, "%.1fs", seconds);
    return;
  }
  /* The design pads single digits ("01s", "02s") so the row keeps its rhythm
   * when the labels cross from one digit to two. */
  BLI_snprintf(out, size, "%02.0fs", seconds);
}

/**
 * Labels sit above the ticks and the ticks hang down to the dock's floor, so
 * the ruler reads as a scale rather than a row of centred marks.
 */
void draw_ruler(const DirectorViewState &state,
                const DirectorTimelineRuntime &runtime,
                const float tick_base)
{
  const float u = UI_SCALE_FAC;
  const float width = BLI_rctf_size_x(&runtime.viewport_bounds);
  const float fps = std::max(state.fps, 0.001f);
  const float pixels_per_second = width * fps / runtime.view_span_frames;
  /* `m:ss` cannot label a sub-second step — every tick would round to the
   * same string — so the minutes unit floors the major step at one second. */
  const float major_seconds = std::max(major_tick_seconds(pixels_per_second),
                                       state.ruler_minutes ? 1.0f : 0.0f);
  const int divisions = major_seconds * pixels_per_second >= 150.0f * u ? 10 : 5;
  const float minor_seconds = major_seconds / float(divisions);
  const float start_seconds = (runtime.view_start_frame - state.scene_frame_start) / fps;
  const float end_seconds = start_seconds + runtime.view_span_frames / fps;
  const float first_tick = std::ceil(start_seconds / minor_seconds) * minor_seconds;

  const float major_h = 26.0f * u;
  const float label_y = tick_base + major_h + 10.0f * u;

  for (float seconds = first_tick; seconds <= end_seconds + minor_seconds * 0.25f;
       seconds += minor_seconds)
  {
    const float frame = state.scene_frame_start + seconds * fps;
    const float t = (frame - runtime.view_start_frame) / runtime.view_span_frames;
    const float x = runtime.viewport_bounds.xmin + t * width;
    const float major_index = std::round(seconds / major_seconds);
    const bool is_major = std::abs(seconds - major_index * major_seconds) < minor_seconds * 0.15f;
    if (is_major) {
      draw_rect(x, tick_base, x + std::max(1.0f, u), tick_base + major_h, RULER_COLOR);
      char label[32];
      ruler_label(state, seconds, major_seconds, label, sizeof(label));
      draw_text(label, x - 2.0f * u, label_y, 12.0f * u, TIME_COLOR);
    }
    else {
      const float dot = std::max(2.0f, 2.0f * u);
      const float dot_y = tick_base + major_h * 0.42f;
      const rctf dot_rect = {
          x - dot * 0.5f, x + dot * 0.5f, dot_y - dot * 0.5f, dot_y + dot * 0.5f};
      draw_round_rect(dot_rect, dot * 0.5f, RULER_MINOR_COLOR);
    }
  }
}

void draw_strip(const DirectorViewState &state,
                DirectorTimelineRuntime *runtime,
                const float strip_y,
                const float strip_h)
{
  runtime->beat_hits.clear();
  BLI_rctf_init(&runtime->strip_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  if (state.beats.is_empty()) {
    return;
  }
  const float width = BLI_rctf_size_x(&runtime->viewport_bounds);
  const auto frame_x = [&](const float frame) {
    return runtime->viewport_bounds.xmin +
           (frame - runtime->view_start_frame) / runtime->view_span_frames * width;
  };
  float raw_start = frame_x(float(state.frame_start));
  float raw_end = frame_x(float(state.frame_end));
  if (state.beats.size() == 1) {
    raw_start -= 9.0f * UI_SCALE_FAC;
    raw_end += 9.0f * UI_SCALE_FAC;
  }
  const float visible_start = std::max(raw_start, runtime->viewport_bounds.xmin);
  const float visible_end = std::min(raw_end, runtime->viewport_bounds.xmax);
  if (visible_end <= visible_start) {
    return;
  }
  runtime->strip_bounds = {visible_start, visible_end, strip_y, strip_y + strip_h};
  const float *strip_color = runtime->strip_hovered ? STRIP_HOVER_COLOR : STRIP_COLOR;
  draw_round_rect(runtime->strip_bounds, 7.0f * UI_SCALE_FAC, strip_color);

  const float font_size = 12.0f * UI_SCALE_FAC;
  const float icon_size = 16.0f * UI_SCALE_FAC;
  const float label_x = visible_start + 27.0f * UI_SCALE_FAC;
  const float label_width = icon_size + 7.0f * UI_SCALE_FAC +
                            text_width(state.camera_name.c_str(), font_size);
  if (visible_end - label_x > label_width) {
    draw_camera_icon(label_x, strip_y + (strip_h - icon_size) * 0.5f, icon_size);
    draw_text(state.camera_name.c_str(),
              label_x + icon_size + 7.0f * UI_SCALE_FAC,
              strip_y + (strip_h - font_size) * 0.5f + 1.0f * UI_SCALE_FAC,
              font_size,
              STRIP_TEXT_COLOR);
  }

  const float handle_w = std::max(9.0f, 11.0f * UI_SCALE_FAC);
  for (const DirectorBeatView &beat : state.beats) {
    const float x = frame_x(float(beat.frame));
    if (x < runtime->viewport_bounds.xmin || x > runtime->viewport_bounds.xmax) {
      continue;
    }
    const rctf handle = {x - handle_w * 0.5f, x + handle_w * 0.5f, strip_y, strip_y + strip_h};
    const bool highlighted = beat.index == state.active_beat_index ||
                             beat.index == runtime->hovered_beat;
    draw_round_rect(handle, handle_w * 0.48f, highlighted ? HANDLE_ACTIVE_COLOR : HANDLE_COLOR);
    DirectorTimelineBeatHit hit;
    hit.bounds = {x - 10.0f * UI_SCALE_FAC,
                  x + 10.0f * UI_SCALE_FAC,
                  strip_y - 4.0f * UI_SCALE_FAC,
                  strip_y + strip_h + 4.0f * UI_SCALE_FAC};
    hit.index = beat.index;
    runtime->beat_hits.append(hit);
  }
}

void draw_playhead(const DirectorViewState &state,
                   const DirectorTimelineRuntime &runtime,
                   const float bottom,
                   const float top)
{
  const float width = BLI_rctf_size_x(&runtime.viewport_bounds);
  const float x = runtime.viewport_bounds.xmin + (state.frame_current - runtime.view_start_frame) /
                                                     runtime.view_span_frames * width;
  if (x < runtime.viewport_bounds.xmin || x > runtime.viewport_bounds.xmax) {
    return;
  }
  const float pill_h = 25.0f * UI_SCALE_FAC;
  const float pill_y = top - pill_h;
  draw_rect(x - 0.5f * UI_SCALE_FAC,
            bottom,
            x + 0.5f * UI_SCALE_FAC,
            pill_y + 2.0f * UI_SCALE_FAC,
            PLAYHEAD_COLOR);

  char label[32];
  const float seconds = (state.frame_current - state.scene_frame_start) /
                        std::max(state.fps, 0.001f);
  BLI_snprintf(label, sizeof(label), "%.2f", seconds);
  const float font_size = 12.0f * UI_SCALE_FAC;
  const float pill_w = text_width(label, font_size) + 22.0f * UI_SCALE_FAC;
  const float center = std::clamp(x,
                                  runtime.viewport_bounds.xmin + pill_w * 0.5f,
                                  runtime.viewport_bounds.xmax - pill_w * 0.5f);
  const rctf pill = {center - pill_w * 0.5f, center + pill_w * 0.5f, pill_y, top};
  draw_round_rect(pill, pill_h * 0.42f, PLAYHEAD_COLOR);
  draw_text(label,
            center - text_width(label, font_size) * 0.5f,
            pill_y + (pill_h - font_size) * 0.5f,
            font_size,
            PLAYHEAD_TEXT_COLOR);
}

}  // namespace

void view3d_director_timeline_draw_content(const ARegion *region,
                                           const DirectorViewState &state,
                                           DirectorTimelineRuntime *runtime,
                                           const int margin,
                                           const int /*unit*/,
                                           const int content_top)
{
  sync_view(state, runtime);
  const float u = UI_SCALE_FAC;
  runtime->viewport_bounds = {float(margin) + 26.0f * u,
                              float(region->winx - margin) - 26.0f * u,
                              float(margin),
                              float(content_top)};
  /* Bottom-up: ruler ticks on the dock floor, labels above them, then the
   * camera strip in the band left under the control row. */
  const float tick_base = float(margin) + 10.0f * u;
  const float label_top = tick_base + 36.0f * u + 12.0f * u;
  const float strip_h = std::min(32.0f * u, std::max(0.0f, content_top - label_top - 8.0f * u));
  const float strip_y = label_top + 6.0f * u;

  draw_ruler(state, *runtime, tick_base);
  draw_strip(state, runtime, strip_y, strip_h);
  draw_playhead(state, *runtime, tick_base, float(content_top) - 6.0f * u);
}
